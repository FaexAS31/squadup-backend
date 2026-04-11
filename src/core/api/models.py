"""
SquadUp - Django Models (Versión Final)
=======================================
Actualizado después de auditoría visual de mockups.

MODELOS AÑADIDOS TRAS REVISIÓN DE UI:
- Memory, MemoryPhoto (pantalla Add Memory, Match Space Enhanced)
- MatchActivity (Timeline en Match Space)
- MeetupPlan (Plan Suggested, Meetup Confirmed)
- BlitzVote (Group Consensus/votación grupal)

CAMPOS AÑADIDOS:
- Profile.interests (tags de intereses)
- Group.is_new (badge "New")
- User stats como properties
"""

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
from datetime import timedelta
import uuid


# =============================================================================
# USER BILLING MIXIN
# =============================================================================
class UserBillingMixin:
    """Métodos de billing para User."""
    
    @property
    def active_subscription(self):
        return self.subscriptions.filter(
            status__in=['trialing', 'active', 'past_due']
        ).order_by('-created_at').first()
    
    @property
    def current_plan(self):
        subscription = self.active_subscription
        return subscription.plan if subscription else None
    
    @property
    def is_premium(self):
        plan = self.current_plan
        return plan and plan.plan_type in ['premium', 'enterprise']
    
    @property
    def is_trialing(self):
        subscription = self.active_subscription
        return subscription and subscription.status == 'trialing'
    
    @property
    def default_payment_method(self):
        return self.payment_methods.filter(
            is_default=True, 
            is_valid=True
        ).first()
    
    def has_feature(self, feature_key: str) -> bool:
        plan = self.current_plan
        if not plan:
            return False
        try:
            feature = plan.features.get(feature_key=feature_key)
            return feature.as_bool
        except PlanFeature.DoesNotExist:
            return False
    
    FREE_FEATURE_DEFAULTS = {
        'max_groups': 3,
        'max_blitz_per_week': 3,
        'max_swipes_per_blitz': 10,
        'max_solo_connections': 5,
    }

    def get_feature_limit(self, feature_key: str) -> int:
        plan = self.current_plan
        if not plan:
            return self.FREE_FEATURE_DEFAULTS.get(feature_key, 0)
        try:
            feature = plan.features.get(feature_key=feature_key)
            return feature.as_int
        except PlanFeature.DoesNotExist:
            return self.FREE_FEATURE_DEFAULTS.get(feature_key, 0)


# =============================================================================
# USER MODEL
# =============================================================================
class User(UserBillingMixin, models.Model):
    """
    Usuario compatible con Firebase Authentication.
    
    ⚠️ AUTENTICACIÓN SOLO VÍA FIREBASE
    
    NO TIENE password ni username. Toda validación de credenciales ocurre en Firebase.
    El campo 'firebase_uid' es la única relación con Firebase Authentication.
    
    ROLES PERMITIDOS (asignados solo por ADMIN vía Django Admin o API):
    - REGULAR (default para nuevos usuarios)
    - SUPPORT (solo para soporte técnico)
    - MANAGER (solo para gestores)
    - ADMIN (super admin, requiere validación manual)
    
    SEGURIDAD:
    - is_staff y is_superuser SIEMPRE False en get_or_create
    - Los permisos se manejan por `role` y `group permissions`
    """
    
    class Roles(models.TextChoices):
        ADMIN = 'ADMIN', 'Super Admin'
        MANAGER = 'MANAGER', 'Manager'
        SUPPORT = 'SUPPORT', 'Soporte'
        REGULAR = 'REGULAR', 'Usuario Regular'
    
    role = models.CharField(
        max_length=20, 
        choices=Roles.choices, 
        default=Roles.REGULAR
    )

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=254, unique=True)
    phone = models.CharField(max_length=16, blank=True, default="")
    
    # Firebase Integration
    firebase_uid = models.CharField(max_length=128, unique=True, db_index=True)
    
    # AÑADIDO: Requerido por RF-003 (User Identification)
    profile_photo = models.URLField(max_length=500, blank=True, default="")
    is_verified = models.BooleanField(default=False)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    # Preferencias para algoritmo de recomendación
    preferences = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['firebase_uid']),
            models.Index(fields=['email']),
            models.Index(fields=['role']),  # ⚡ AÑADIDO para filtrado por rol
            models.Index(fields=['is_active']),  # ⚡ AÑADIDO para usuarios activos
            models.Index(fields=['created_at']),  # ⚡ AÑADIDO para paginación temporal
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def is_authenticated(self):
        """
        Retorna True si el usuario está autenticado (siempre True para usuarios válidos en DB).
        Requerido por DRF para compatibilidad con check_permissions.
        """
        return True
    
    @property
    def username(self):
        """Retorna el firebase_uid como username para compatibilidad."""
        return self.firebase_uid
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def initials(self):
        """Para el avatar con iniciales (mockup Profile: 'FM')"""
        return f"{self.first_name[0]}{self.last_name[0]}".upper()
    
    # =========================================================================
    # STATS - Vistos en mockup Profile (12 Matches, 3 Groups, 28 Memories)
    # =========================================================================
    @property
    def total_matches(self):
        """Cuenta matches donde el usuario participó."""
        from django.db.models import Q
        return Match.objects.filter(
            Q(blitz_1__group__members=self) | Q(blitz_2__group__members=self),
            status__in=['active', 'chatting', 'met']
        ).distinct().count()
    
    @property
    def total_groups(self):
        """Grupos donde el usuario es miembro."""
        return self.groups.filter(is_active=True).count()
    
    @property
    def total_memories(self):
        """Memories creadas por el usuario."""
        return Memory.objects.filter(created_by=self).count()


# =============================================================================
# PROFILE MODEL
# =============================================================================
class Profile(models.Model):
    """
    Perfil extendido del usuario.
    
    AÑADIDO tras mockup:
    - interests: Lista de intereses (Gaming, Music, Coffee, Fitness)
    """
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='profile'
    )
    
    bio = models.TextField(blank=True, default="")
    
    # AÑADIDO: Intereses del usuario (visto en mockup Profile y Friends)
    # Estructura: ["Gaming", "Music", "Coffee", "Fitness"]
    interests = models.JSONField(
        default=list, 
        blank=True,
        help_text="Lista de intereses/tags del usuario"
    )
    
    # Datos demográficos opcionales
    age = models.PositiveIntegerField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default="")
    
    # Ubicación preferida (para heat map y descubrimiento)
    default_location = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Ubicación por defecto: {lat, lng, city}"
    )
    
    extra_data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'profiles'

    def __str__(self):
        return f"Profile of {self.user}"


# =============================================================================
# PROFILE PHOTO MODEL (Gallery photos for user profile)
# =============================================================================
class ProfilePhoto(models.Model):
    """
    Gallery photos for user profile (up to 6 per user).

    Main profile photo is stored in User.profile_photo.
    This model stores additional display photos shown in the profile gallery.
    Images are hosted on Firebase Storage, URLs stored here.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='gallery_photos'
    )
    image_url = models.URLField(
        max_length=500,
        help_text="Full-size image URL from Firebase Storage"
    )
    thumbnail_url = models.URLField(
        max_length=500,
        blank=True,
        default="",
        help_text="Thumbnail URL for faster loading in lists"
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order (0 = first)"
    )
    caption = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional caption for the photo"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'profile_photos'
        ordering = ['order', 'created_at']
        indexes = [
            models.Index(fields=['user', 'order']),
        ]

    def __str__(self):
        return f"Photo {self.order} for {self.user}"


# =============================================================================
# FRIENDSHIP MODEL
# =============================================================================
class Friendship(models.Model):
    """
    Gestión de amigos (RF-004).
    Mockup: Friends list con nombre e intereses.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        ACCEPTED = 'accepted', 'Aceptado'
        REJECTED = 'rejected', 'Rechazado'
        BLOCKED = 'blocked', 'Bloqueado'

    class Source(models.TextChoices):
        DIRECT = 'direct', 'Directo'
        SOLO = 'solo', 'Solo Mode'

    user_from = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='friendships_initiated'
    )
    user_to = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='friendships_received'
    )
    status = models.CharField(
        max_length=20, 
        choices=Status.choices, 
        default=Status.PENDING
    )
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.DIRECT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'friendships'
        unique_together = ('user_from', 'user_to')
        indexes = [
            models.Index(fields=['user_from', 'status']),
            models.Index(fields=['user_to', 'status']),
        ]

    def __str__(self):
        return f"{self.user_from} -> {self.user_to} ({self.status})"


# =============================================================================
# GROUP MODEL
# =============================================================================
class Group(models.Model):
    """
    Grupo de usuarios para Blitz.
    
    AÑADIDO tras mockup:
    - is_new: Badge "New" en Home Hub
    - color: Color del avatar del grupo (visto en mockups)
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    image_url = models.URLField(max_length=500, blank=True, null=True, default="", help_text="Group image URL")
    
    creator = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='created_groups'
    )
    
    members = models.ManyToManyField(
        User, 
        through='GroupMembership',
        related_name='groups'
    )
    
    # AÑADIDO: Color del grupo para avatar (mockup muestra círculos de colores)
    # Estructura: {"primary": "#FF6B6B", "secondary": "#4ECDC4"}
    colors = models.JSONField(
        default=dict,
        blank=True,
        help_text="Colores del avatar del grupo"
    )
    
    # AÑADIDO: Para mostrar badge "New" en Home Hub
    is_new = models.BooleanField(
        default=True,
        help_text="Mostrar badge 'New' (se desactiva después de X días)"
    )
    
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    # Invite code for sharing group links
    invite_code = models.CharField(
        max_length=12,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Unique code for invite links (auto-generated)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'groups'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = self._generate_invite_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_invite_code():
        """Generate a unique 8-character invite code."""
        import secrets
        import string
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(secrets.choice(alphabet) for _ in range(8))
            if not Group.objects.filter(invite_code=code).exists():
                return code

    def regenerate_invite_code(self):
        """Regenerate the invite code (useful if compromised)."""
        self.invite_code = self._generate_invite_code()
        self.save(update_fields=['invite_code'])
        return self.invite_code

    @property
    def member_count(self):
        return self.members.count()
    
    @property
    def combined_interests(self):
        """
        Unión de intereses de todos los miembros.
        Visto en mockup: "Combined Interests" en Create Group y Group Detail.
        """
        interests = set()
        for member in self.members.all():
            if hasattr(member, 'profile') and member.profile.interests:
                profile_interests = member.profile.interests
                if isinstance(profile_interests, str):
                    profile_interests = [i.strip() for i in profile_interests.split(',') if i.strip()]
                interests.update(profile_interests)
        return list(interests)
    
    @property
    def leader(self):
        """Retorna el Blitz Leader del grupo."""
        membership = self.groupmembership_set.filter(role='admin').first()
        return membership.user if membership else self.creator
    
    # STATS vistas en mockup Group Detail
    @property
    def total_matches(self):
        from django.db.models import Q
        return Match.objects.filter(
            Q(blitz_1__group=self) | Q(blitz_2__group=self),
            status__in=['active', 'chatting', 'met']
        ).distinct().count()
    
    @property
    def total_outings(self):
        """Outings = Meetups confirmados."""
        from django.db.models import Q
        return MeetupPlan.objects.filter(
            Q(match__blitz_1__group=self) | Q(match__blitz_2__group=self),
            status='completed'
        ).count()
    
    @property
    def total_memories(self):
        from django.db.models import Q
        return Memory.objects.filter(
            Q(match__blitz_1__group=self) | Q(match__blitz_2__group=self)
        ).count()


# =============================================================================
# GROUP MEMBERSHIP
# =============================================================================
class GroupMembership(models.Model):
    """
    Relación User-Group con rol.
    Mockup: "Leader" vs "Member" badges.
    """
    class Role(models.TextChoices):
        MEMBER = 'member', 'Miembro'
        ADMIN = 'admin', 'Líder'  # Blitz Leader
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'group_memberships'
        unique_together = ('user', 'group')

    def __str__(self):
        return f"{self.user} in {self.group} ({self.role})"
    
    @property
    def is_leader(self):
        return self.role == self.Role.ADMIN


# =============================================================================
# GROUP INVITATION
# =============================================================================
class GroupInvitation(models.Model):
    """
    Invitación pendiente a un grupo. El usuario debe aceptar/rechazar
    antes de convertirse en miembro.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        ACCEPTED = 'accepted', 'Aceptada'
        DECLINED = 'declined', 'Rechazada'
        EXPIRED = 'expired', 'Expirada'

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='invitations')
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_invitations')
    invitee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_invitations')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'group_invitations'
        indexes = [
            models.Index(fields=['invitee', 'status']),
            models.Index(fields=['group', 'status']),
        ]

    def __str__(self):
        return f"Invitation: {self.inviter} → {self.invitee} for {self.group} ({self.status})"


# =============================================================================
# BLITZ MODEL
# =============================================================================
BLITZ_DEFAULT_DURATION_MINUTES = 60


class Blitz(models.Model):
    """
    Sesión Blitz - Disponibilidad temporal de un grupo.
    Mockup: Timer "LIVE 14:32", estado activo.
    """
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Activo'
        EXPIRED = 'expired', 'Expirado'
        CANCELLED = 'cancelled', 'Cancelado'
        MATCHED = 'matched', 'Emparejado'
    
    group = models.ForeignKey(
        Group, 
        on_delete=models.CASCADE, 
        related_name='blitz_sessions'
    )
    
    leader = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='led_blitz_sessions'
    )
    
    status = models.CharField(
        max_length=20, 
        choices=Status.choices, 
        default=Status.ACTIVE
    )
    
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    
    # Ubicación
    location = models.JSONField(
        default=dict,
        help_text="Estructura: {lat, lng, address, radius_km}"
    )
    
    activity_type = models.CharField(max_length=100, blank=True, default="")
    min_opponent_size = models.PositiveSmallIntegerField(default=2)
    max_opponent_size = models.PositiveSmallIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class SwipeMode(models.TextChoices):
        LEADER = 'leader', 'Solo líder'
        DEMOCRATIC = 'democratic', 'Democrático'

    swipe_mode = models.CharField(
        max_length=20,
        choices=SwipeMode.choices,
        default=SwipeMode.LEADER,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'blitz_sessions'
        verbose_name_plural = 'Blitz Sessions'
        indexes = [
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Blitz: {self.group.name} ({self.status})"
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=BLITZ_DEFAULT_DURATION_MINUTES)
        super().save(*args, **kwargs)
    
    @property
    def is_expired(self):
        return timezone.now() > self.expires_at or self.status != self.Status.ACTIVE
    
    @property
    def time_remaining_seconds(self):
        """Para el timer 'LIVE 14:32' del mockup."""
        if self.is_expired:
            return 0
        delta = self.expires_at - timezone.now()
        return max(0, int(delta.total_seconds()))
    
    @property
    def time_remaining_display(self):
        """Formato MM:SS para UI."""
        seconds = self.time_remaining_seconds
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"


# =============================================================================
# BLITZ INTERACTION
# =============================================================================
class BlitzInteraction(models.Model):
    """
    Interacciones like/skip entre grupos.
    """
    class InteractionType(models.TextChoices):
        LIKE = 'like', 'Like'
        SKIP = 'skip', 'Skip'
    
    from_blitz = models.ForeignKey(
        Blitz, 
        on_delete=models.CASCADE, 
        related_name='interactions_made'
    )
    to_blitz = models.ForeignKey(
        Blitz, 
        on_delete=models.CASCADE, 
        related_name='interactions_received'
    )
    interaction_type = models.CharField(max_length=10, choices=InteractionType.choices)
    
    # AÑADIDO: Para saber si requiere votación grupal
    requires_consensus = models.BooleanField(
        default=False,
        help_text="Si True, requiere aprobación de miembros del grupo"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'blitz_interactions'
        unique_together = ('from_blitz', 'to_blitz')

    def __str__(self):
        return f"{self.from_blitz.group.name} -> {self.to_blitz.group.name}: {self.interaction_type}"
    
    @property
    def consensus_status(self):
        """
        Estado del consenso grupal (mayoría simple >50%).
        Votos pendientes por más de 3 minutos se cuentan como rechazo
        para evitar bloqueos por miembros offline.
        """
        if not self.requires_consensus:
            return 'approved'

        from django.utils import timezone as tz
        from datetime import timedelta

        votes = self.votes.all()
        total_members = self.from_blitz.group.member_count
        majority = (total_members // 2) + 1
        vote_timeout = tz.now() - timedelta(minutes=3)

        approved = 0
        rejected = 0
        for v in votes:
            if v.vote == 'approved':
                approved += 1
            elif v.vote == 'rejected':
                rejected += 1
            elif v.vote == 'pending' and v.created_at < vote_timeout:
                # Treat timed-out votes as rejections
                rejected += 1

        if approved >= majority:
            return 'approved'
        if rejected >= majority:
            return 'rejected'
        return 'pending'


# =============================================================================
# BLITZ VOTE (NUEVO - Group Consensus)
# =============================================================================
class BlitzVote(models.Model):
    """
    NUEVO MODELO - Visto en mockup "Group Consensus"
    
    Permite que cada miembro del grupo vote sobre un like.
    Mockup muestra: "2 of 3 members approved", estados "Approved"/"Pending"
    """
    class VoteChoice(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        APPROVED = 'approved', 'Aprobado'
        REJECTED = 'rejected', 'Rechazado'
    
    interaction = models.ForeignKey(
        BlitzInteraction,
        on_delete=models.CASCADE,
        related_name='votes'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='blitz_votes'
    )
    vote = models.CharField(
        max_length=20,
        choices=VoteChoice.choices,
        default=VoteChoice.PENDING
    )
    voted_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'blitz_votes'
        unique_together = ('interaction', 'user')

    def __str__(self):
        return f"{self.user} voted {self.vote} on {self.interaction}"


# =============================================================================
# MATCH MODEL
# =============================================================================
class Match(models.Model):
    """
    Match entre dos grupos.
    
    AÑADIDO tras mockup:
    - matched_at: Fecha específica del match ("Matched Jan 20")
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'  # AÑADIDO: Tab "Pending" en Matches
        ACTIVE = 'active', 'Activo'
        CHATTING = 'chatting', 'En Chat'
        MET = 'met', 'Se Encontraron'
        PAST = 'past', 'Pasado'  # AÑADIDO: Tab "Past" en Matches
        EXPIRED = 'expired', 'Expirado'
        CANCELLED = 'cancelled', 'Cancelado'
    
    blitz_1 = models.ForeignKey(
        Blitz, 
        on_delete=models.CASCADE, 
        related_name='matches_as_first'
    )
    blitz_2 = models.ForeignKey(
        Blitz, 
        on_delete=models.CASCADE, 
        related_name='matches_as_second'
    )
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )
    
    # AÑADIDO: Fecha del match para mostrar "Matched Jan 20"
    matched_at = models.DateTimeField(default=timezone.now)
    
    chat = models.OneToOneField(
        'Chat', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='match'
    )
    
    meeting_location = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'matches'
        verbose_name_plural = 'Matches'
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['status', 'matched_at']),
        ]

    def __str__(self):
        return f"Match: {self.blitz_1.group.name} <-> {self.blitz_2.group.name}"
    
    @property
    def days_together(self):
        """Para mostrar '56d Together' en mockup Match Space Enhanced."""
        delta = timezone.now() - self.matched_at
        return delta.days
    
    @property
    def common_interests(self):
        """Intereses en común entre ambos grupos."""
        interests_1 = set(self.blitz_1.group.combined_interests)
        interests_2 = set(self.blitz_2.group.combined_interests)
        return list(interests_1.intersection(interests_2))
    
    @property
    def common_interests_count(self):
        """'3 common interests' en mockup."""
        return len(self.common_interests)


# =============================================================================
# MATCH ACTIVITY (NUEVO - Timeline)
# =============================================================================
class MatchActivity(models.Model):
    """
    NUEVO MODELO - Timeline visto en mockup "Match Space"
    
    Registra eventos: Match Created, Chat Started, Plan Suggested, Meetup Confirmed
    """
    class ActivityType(models.TextChoices):
        MATCH_CREATED = 'match_created', 'Match Created'
        CHAT_STARTED = 'chat_started', 'Chat Started'
        PLAN_SUGGESTED = 'plan_suggested', 'Plan Suggested'
        PLAN_ACCEPTED = 'plan_accepted', 'Plan Accepted'
        MEETUP_CONFIRMED = 'meetup_confirmed', 'Meetup Confirmed'
        MEETUP_COMPLETED = 'meetup_completed', 'Meetup Completed'
        MEMORY_ADDED = 'memory_added', 'Memory Added'
        PHOTO_SHARED = 'photo_shared', 'Photo Shared'
    
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    
    activity_type = models.CharField(max_length=30, choices=ActivityType.choices)
    
    # Usuario que generó la actividad (si aplica)
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='match_activities'
    )
    
    # Descripción para mostrar en timeline
    description = models.CharField(max_length=500, blank=True, default="")
    
    # Datos adicionales (ej: ID del plan, mensaje, etc.)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'match_activities'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.match}: {self.activity_type}"


# =============================================================================
# MEETUP PLAN (NUEVO)
# =============================================================================
class MeetupPlan(models.Model):
    """
    NUEVO MODELO - Visto en mockup Match Space Timeline
    
    "Plan Suggested", "Meetup Confirmed" con fecha/hora específica.
    Mockup: "Jamie proposed meeting at The Blue Note", "Saturday, Jan 25 at 7 PM"
    """
    class Status(models.TextChoices):
        PROPOSED = 'proposed', 'Propuesto'
        ACCEPTED = 'accepted', 'Aceptado'
        CONFIRMED = 'confirmed', 'Confirmado'
        COMPLETED = 'completed', 'Completado'
        CANCELLED = 'cancelled', 'Cancelado'
    
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='meetup_plans'
    )
    
    proposed_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='proposed_meetups'
    )
    
    title = models.CharField(
        max_length=200,
        help_text="Ej: 'Meeting at The Blue Note'"
    )
    
    # Fecha y hora del meetup
    scheduled_at = models.DateTimeField()
    
    # Ubicación
    location_name = models.CharField(max_length=200, blank=True, default="")
    location_address = models.TextField(blank=True, default="")
    location_coords = models.JSONField(
        default=dict,
        blank=True,
        help_text="{lat, lng}"
    )
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROPOSED
    )
    
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'meetup_plans'
        ordering = ['-scheduled_at']

    def __str__(self):
        return f"{self.title} - {self.scheduled_at}"


# =============================================================================
# MEMORY MODEL (NUEVO)
# =============================================================================
class Memory(models.Model):
    """
    NUEVO MODELO - Visto en mockups "Add Memory" y "Match Space Enhanced"
    
    Permite guardar recuerdos de outings con fotos y notas.
    Mockup muestra: Memory Type (Outing/Photo/Note), Title, Date, Photos, Notes
    """
    class MemoryType(models.TextChoices):
        OUTING = 'outing', 'Outing'
        PHOTO = 'photo', 'Photo'
        NOTE = 'note', 'Note'
    
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='memories'
    )
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,  #  CAMBIADO: Conserva memoria pero user=None
        null=True,
        blank=True,
        related_name='created_memories'
    )
    
    memory_type = models.CharField(
        max_length=20,
        choices=MemoryType.choices,
        default=MemoryType.OUTING
    )
    
    title = models.CharField(max_length=200)
    
    # Fecha del evento (puede ser diferente a created_at)
    event_date = models.DateField()
    
    notes = models.TextField(blank=True, default="")
    
    # Ubicación del evento (opcional)
    location_name = models.CharField(max_length=200, blank=True, default="")
    
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'memories'
        verbose_name_plural = 'Memories'
        ordering = ['-event_date']

    def __str__(self):
        return f"{self.title} ({self.memory_type})"
    
    @property
    def photo_count(self):
        """Para mostrar '5 photos' en mockup."""
        return self.photos.count()


# =============================================================================
# MEMORY PHOTO (NUEVO)
# =============================================================================
class MemoryPhoto(models.Model):
    """
    NUEVO MODELO - Fotos asociadas a un Memory.
    Mockup "Add Memory" muestra grid de fotos.
    """
    memory = models.ForeignKey(
        Memory,
        on_delete=models.CASCADE,
        related_name='photos'
    )
    
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='uploaded_photos'
    )
    
    # URL de la imagen (almacenada en Firebase Storage, S3, etc.)
    image_url = models.URLField(max_length=500)
    
    # Thumbnail para carga rápida
    thumbnail_url = models.URLField(max_length=500, blank=True, default="")
    
    caption = models.CharField(max_length=500, blank=True, default="")
    
    # Orden de la foto en la galería
    order = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'memory_photos'
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"Photo for {self.memory.title}"


# =============================================================================
# CHAT MODEL
# =============================================================================
class Chat(models.Model):
    """
    Chat temporal para coordinación.
    Mockup muestra: "7 members • 3 online"
    """
    participants = models.ManyToManyField(User, related_name='chats')
    
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    # AÑADIDO: Último mensaje para preview
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(max_length=100, blank=True, default="")
    
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chats'

    def __str__(self):
        return f"Chat {self.id}"
    
    @property
    def participant_count(self):
        """'7 members' en mockup."""
        return self.participants.count()


# =============================================================================
# MESSAGE MODEL
# =============================================================================
class Message(models.Model):
    """
    Mensaje en un chat.
    Mockup: Avatar, nombre, texto, timestamp.
    """
    class MessageType(models.TextChoices):
        TEXT = 'text', 'Texto'
        IMAGE = 'image', 'Imagen'
        AUDIO = 'audio', 'Audio'
        LOCATION = 'location', 'Ubicación'
        SYSTEM = 'system', 'Sistema'
    
    chat = models.ForeignKey(
        Chat, 
        on_delete=models.CASCADE, 
        related_name='messages'
    )
    
    sender = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL,  #  Conserva mensaje con sender=None
        null=True,
        blank=True,
        related_name='sent_messages'
    )
    
    text = models.TextField(default="")
    image_url = models.URLField(max_length=500, blank=True, default="")
    audio_url = models.URLField(max_length=500, blank=True, default="")
    message_type = models.CharField(
        max_length=20, 
        choices=MessageType.choices, 
        default=MessageType.TEXT
    )
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at']
        models.Index(fields=['sender', 'created_at']),  # ⚡ AÑADIDO
        models.Index(fields=['is_read', 'created_at']),  # ⚡ AÑADIDO
        indexes = [
            models.Index(fields=['chat', 'created_at']),
        ]

    def __str__(self):
        return f"{self.sender}: {self.text[:30]}..."


# =============================================================================
# NOTIFICATION MODEL
# =============================================================================
class Notification(models.Model):
    """Notificaciones push y in-app."""
    
    class NotificationType(models.TextChoices):
        BLITZ_MATCH = 'blitz_match', 'Nuevo Match'
        BLITZ_LIKE = 'blitz_like', 'Grupo te dio Like'
        BLITZ_VOTE_REQUEST = 'blitz_vote_request', 'Votación Pendiente'
        NEW_MESSAGE = 'new_message', 'Nuevo Mensaje'
        FRIEND_REQUEST = 'friend_request', 'Solicitud de Amistad'
        GROUP_INVITE = 'group_invite', 'Invitación a Grupo'
        MEETUP_PROPOSED = 'meetup_proposed', 'Plan Propuesto'
        MEETUP_CONFIRMED = 'meetup_confirmed', 'Meetup Confirmado'
        BLITZ_EXPIRING = 'blitz_expiring', 'Blitz por Expirar'
        SOLO_CONNECTION = 'solo_connection', 'Conexión Solo Mode'
        SOLO_MATCH = 'solo_match', 'Match Solo Mode'
        MEMORY_ADDED = 'memory_added', 'Recuerdo Agregado'
        SYSTEM = 'system', 'Sistema'
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='notifications'
    )
    
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    title = models.CharField(max_length=200)
    body = models.TextField()
    
    data = models.JSONField(default=dict, blank=True)
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    fcm_sent = models.BooleanField(default=False)
    fcm_sent_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', 'created_at']),
        ]

    def __str__(self):
        return f"{self.notification_type}: {self.title}"


# =============================================================================
# DEVICE TOKEN - FCM Push Notification Tokens
# =============================================================================
class DeviceToken(models.Model):
    """
    Stores FCM device tokens for push notifications.
    Each user can have multiple tokens (multiple devices).
    """
    PLATFORM_CHOICES = [
        ('ios', 'iOS'),
        ('android', 'Android'),
        ('web', 'Web'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='device_tokens'
    )
    token = models.CharField(max_length=500, unique=True)
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES, default='ios')
    device_id = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'device_tokens'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['token']),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.platform} ({self.token[:20]}...)"


# =============================================================================
# LOCATION LOG - Para Heat Map
# =============================================================================
class LocationLog(models.Model):
    """
    Registro de ubicaciones para Heat Map.
    Mockup: Clusters con "3 groups", "8 groups", estadísticas de zona.
    """
    blitz = models.ForeignKey(
        Blitz, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='location_logs'
    )
    match = models.ForeignKey(
        Match, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='location_logs'
    )
    
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    
    event_type = models.CharField(max_length=50)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'location_logs'
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['created_at']),
        ]


# =============================================================================
# ZONE STATS (NUEVO - Heat Map Premium)
# =============================================================================
class ZoneStats(models.Model):
    """
    NUEVO MODELO - Estadísticas por zona para Heat Map Premium.
    
    Mockup "Heat Map Premium" muestra:
    - 12 Groups LIVE
    - 47 People
    - 8pm Peak Hour
    - Hourly Trend (gráfico de barras)
    """
    # Identificador de zona (puede ser geohash o nombre)
    zone_id = models.CharField(max_length=50, db_index=True)
    zone_name = models.CharField(max_length=100)  # "Downtown District"
    
    # Coordenadas del centro de la zona
    center_lat = models.DecimalField(max_digits=9, decimal_places=6)
    center_lng = models.DecimalField(max_digits=9, decimal_places=6)
    
    # Stats actuales (se actualizan periódicamente)
    groups_live = models.PositiveIntegerField(default=0)
    people_count = models.PositiveIntegerField(default=0)
    
    # Peak hour (0-23)
    peak_hour = models.PositiveSmallIntegerField(null=True, blank=True)
    
    # Trend por hora: {"5pm": 2, "6pm": 4, "7pm": 8, ...}
    hourly_trend = models.JSONField(default=dict, blank=True)
    
    # Nivel de actividad
    activity_level = models.CharField(
        max_length=20,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        default='low'
    )
    
    # Fecha de las estadísticas
    stats_date = models.DateField()
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'zone_stats'
        unique_together = ('zone_id', 'stats_date')
        indexes = [
            models.Index(fields=['stats_date', 'activity_level']),
        ]

    def __str__(self):
        return f"{self.zone_name}: {self.groups_live} groups"


# =============================================================================
# BILLING MODELS
# =============================================================================

class Plan(models.Model):
    """Plan de suscripción (Free, Premium)."""
    
    class BillingInterval(models.TextChoices):
        WEEKLY = 'weekly', 'Semanal'
        MONTHLY = 'monthly', 'Mensual'
        YEARLY = 'yearly', 'Anual'
        LIFETIME = 'lifetime', 'Vitalicio'
    
    class PlanType(models.TextChoices):
        FREE = 'free', 'Gratuito'
        PREMIUM = 'premium', 'Premium'
        ENTERPRISE = 'enterprise', 'Empresarial'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    external_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, default="")
    plan_type = models.CharField(max_length=20, choices=PlanType.choices, default=PlanType.FREE)
    
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    currency = models.CharField(max_length=3, default='USD')
    billing_interval = models.CharField(
        max_length=20,
        choices=BillingInterval.choices,
        default=BillingInterval.MONTHLY
    )
    
    trial_days = models.PositiveIntegerField(default=0)
    
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_plans'
        ordering = ['display_order', 'price']

    def __str__(self):
        return f"{self.name} ({self.price} {self.currency})"
    
    @property
    def is_free(self):
        return self.plan_type == self.PlanType.FREE
    
    @property
    def interval_days(self):
        intervals = {'weekly': 7, 'monthly': 30, 'yearly': 365, 'lifetime': 36500}
        return intervals.get(self.billing_interval, 30)


class PlanFeature(models.Model):
    """
    Features por plan.
    
    ACTUALIZADO según mockup Premium:
    - max_blitz_per_week: 3 (Free) / unlimited (Premium)
    - max_groups: 1 (Free) / 5 (Premium)
    - basic_heat_map / full_heat_map
    - zone_analytics: false (Free) / true (Premium)
    - priority_matching: false (Free) / true (Premium)
    """
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='features')
    feature_key = models.CharField(max_length=100)
    feature_name = models.CharField(max_length=200)
    value = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    
    # AÑADIDO: Para mostrar en UI con ✓ o ✗
    is_highlighted = models.BooleanField(
        default=False,
        help_text="Si mostrar destacado en página de precios"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_plan_features'
        unique_together = ('plan', 'feature_key')

    def __str__(self):
        return f"{self.plan.name}: {self.feature_key} = {self.value}"
    
    @property
    def as_bool(self):
        return self.value.lower() in ('true', '1', 'yes', 'unlimited')
    
    @property
    def as_int(self):
        if self.value.lower() == 'unlimited':
            return -1
        try:
            return int(self.value)
        except ValueError:
            return 0


class Subscription(models.Model):
    """Suscripción de usuario a un plan."""
    
    class Status(models.TextChoices):
        TRIALING = 'trialing', 'En Prueba'
        ACTIVE = 'active', 'Activa'
        PAST_DUE = 'past_due', 'Pago Vencido'
        UNPAID = 'unpaid', 'Impaga'
        CANCELED = 'canceled', 'Cancelada'
        EXPIRED = 'expired', 'Expirada'
        PAUSED = 'paused', 'Pausada'
    
    class CancelReason(models.TextChoices):
        USER_REQUEST = 'user_request', 'Solicitud del Usuario'
        PAYMENT_FAILED = 'payment_failed', 'Pago Fallido'
        FRAUD = 'fraud', 'Fraude Detectado'
        ADMIN = 'admin', 'Cancelado por Admin'
        UPGRADED = 'upgraded', 'Upgrade a Otro Plan'
        DOWNGRADED = 'downgraded', 'Downgrade a Otro Plan'
        OTHER = 'other', 'Otro'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='subscriptions')
    
    external_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    
    started_at = models.DateTimeField(default=timezone.now)
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(blank=True, null=True)
    
    trial_start = models.DateTimeField(null=True, blank=True)
    trial_end = models.DateTimeField(null=True, blank=True)
    
    canceled_at = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    cancel_reason = models.CharField(max_length=30, choices=CancelReason.choices, null=True, blank=True)
    
    grace_period_end = models.DateTimeField(null=True, blank=True)
    
    default_payment_method = models.ForeignKey(
        'PaymentMethod',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subscriptions'
    )
    
    billing_cycle_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_subscriptions'
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'current_period_end']),
        ]

    def __str__(self):
        return f"{self.user} - {self.plan.name} ({self.status})"
    
    def save(self, *args, **kwargs):
        if not self.current_period_end:
            self.current_period_end = self.current_period_start + timedelta(days=self.plan.interval_days)
        super().save(*args, **kwargs)
    
    @property
    def is_active(self):
        return self.status in ['trialing', 'active', 'past_due']


class PaymentMethod(models.Model):
    """Métodos de pago del usuario."""
    
    class Provider(models.TextChoices):
        STRIPE = 'stripe', 'Stripe'
        PAYPAL = 'paypal', 'PayPal'
        MERCADOPAGO = 'mercadopago', 'MercadoPago'
        APPLE = 'apple', 'Apple Pay'
        GOOGLE = 'google', 'Google Pay'
    
    class MethodType(models.TextChoices):
        CARD = 'card', 'Tarjeta'
        PAYPAL = 'paypal', 'PayPal'
        BANK_TRANSFER = 'bank_transfer', 'Transferencia'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
    
    provider = models.CharField(max_length=30, choices=Provider.choices)
    external_id = models.CharField(max_length=255)
    method_type = models.CharField(max_length=30, choices=MethodType.choices)
    
    last_four = models.CharField(max_length=4, blank=True, default="")
    card_brand = models.CharField(max_length=50, blank=True, default="")
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    
    billing_email = models.EmailField(blank=True, default="")
    
    is_default = models.BooleanField(default=False)
    is_valid = models.BooleanField(default=True)
    
    billing_address = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_payment_methods'
        indexes = [
            models.Index(fields=['user', 'is_default']),
        ]

    def __str__(self):
        return f"{self.card_brand} ****{self.last_four}" if self.last_four else f"{self.method_type}"


class Invoice(models.Model):
    """Facturas."""
    
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Borrador'
        OPEN = 'open', 'Abierta'
        PAID = 'paid', 'Pagada'
        VOID = 'void', 'Anulada'
        UNCOLLECTIBLE = 'uncollectible', 'Incobrable'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_number = models.CharField(max_length=50, unique=True)
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    subscription = models.ForeignKey(
        Subscription, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    
    external_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    
    currency = models.CharField(max_length=3, default='USD')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    invoice_date = models.DateTimeField(default=timezone.now)
    due_date = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    
    billing_name = models.CharField(max_length=200, blank=True, default="")
    billing_email = models.EmailField(blank=True, default="")
    billing_address = models.JSONField(default=dict, blank=True)
    
    pdf_url = models.URLField(max_length=500, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_invoices'
        ordering = ['-invoice_date']

    def __str__(self):
        return f"{self.invoice_number} - {self.total} {self.currency}"


class InvoiceItem(models.Model):
    """Líneas de factura."""
    
    class ItemType(models.TextChoices):
        SUBSCRIPTION = 'subscription', 'Suscripción'
        PRORATION = 'proration', 'Prorrateo'
        ONE_TIME = 'one_time', 'Cargo Único'
        DISCOUNT = 'discount', 'Descuento'
        TAX = 'tax', 'Impuesto'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    description = models.CharField(max_length=500)
    
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True)
    
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_invoice_items'


class Payment(models.Model):
    """Intentos de pago."""
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        PROCESSING = 'processing', 'Procesando'
        SUCCEEDED = 'succeeded', 'Exitoso'
        FAILED = 'failed', 'Fallido'
        CANCELED = 'canceled', 'Cancelado'
        REFUNDED = 'refunded', 'Reembolsado'
    
    class FailureReason(models.TextChoices):
        INSUFFICIENT_FUNDS = 'insufficient_funds', 'Fondos Insuficientes'
        CARD_DECLINED = 'card_declined', 'Tarjeta Rechazada'
        EXPIRED_CARD = 'expired_card', 'Tarjeta Expirada'
        PROCESSING_ERROR = 'processing_error', 'Error de Procesamiento'
        OTHER = 'other', 'Otro'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True, related_name='payments'
    )
    
    provider = models.CharField(max_length=30)
    external_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    
    currency = models.CharField(max_length=3, default='USD')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    amount_refunded = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    failure_reason = models.CharField(max_length=50, choices=FailureReason.choices, null=True, blank=True)
    failure_message = models.TextField(blank=True, default="")
    
    attempt_number = models.PositiveSmallIntegerField(default=1)
    processed_at = models.DateTimeField(null=True, blank=True)
    receipt_url = models.URLField(max_length=500, blank=True, default="")
    
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_payments'
        ordering = ['-created_at']


class Coupon(models.Model):
    """Cupones de descuento."""
    
    class DiscountType(models.TextChoices):
        PERCENTAGE = 'percentage', 'Porcentaje'
        FIXED_AMOUNT = 'fixed_amount', 'Monto Fijo'
    
    class Duration(models.TextChoices):
        ONCE = 'once', 'Una Vez'
        REPEATING = 'repeating', 'Repetitivo'
        FOREVER = 'forever', 'Para Siempre'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    code = models.CharField(max_length=50, unique=True, db_index=True)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    
    duration = models.CharField(max_length=20, choices=Duration.choices)
    duration_in_months = models.PositiveIntegerField(null=True, blank=True)
    
    max_redemptions = models.PositiveIntegerField(null=True, blank=True)
    times_redeemed = models.PositiveIntegerField(default=0)
    
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    
    applicable_plans = models.ManyToManyField(Plan, blank=True, related_name='coupons')
    
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_coupons'

    def __str__(self):
        return f"{self.code}: {self.amount}{'%' if self.discount_type == 'percentage' else ''}"


class Discount(models.Model):
    """Descuento aplicado a una suscripción."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='discounts')
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='discounts')
    
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)
    remaining_months = models.PositiveIntegerField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_discounts'


class UsageRecord(models.Model):
    """Tracking de uso para límites por plan."""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name='usage_records')
    
    feature_key = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(default=1)
    
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'billing_usage_records'


class WebhookLog(models.Model):
    """Log de webhooks recibidos."""
    
    class Status(models.TextChoices):
        RECEIVED = 'received', 'Recibido'
        PROCESSING = 'processing', 'Procesando'
        PROCESSED = 'processed', 'Procesado'
        FAILED = 'failed', 'Fallido'
        IGNORED = 'ignored', 'Ignorado'
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    provider = models.CharField(max_length=30)
    event_id = models.CharField(max_length=255, db_index=True)
    event_type = models.CharField(max_length=100)
    
    payload = models.JSONField()
    headers = models.JSONField(default=dict, blank=True)
    
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    error_message = models.TextField(blank=True, default="")
    
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'billing_webhook_logs'
        indexes = [
            models.Index(fields=['provider', 'event_id']),
        ]


# =============================================================================
# MATCH MUTE MODEL
# =============================================================================
class MatchMute(models.Model):
    """
    Silenciar notificaciones de un match específico.
    Permite al usuario silenciar notificaciones sin salirse del match.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='muted_matches'
    )
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name='mutes'
    )
    muted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'match_mutes'
        unique_together = ('user', 'match')
        indexes = [
            models.Index(fields=['user', 'match']),
        ]

    def __str__(self):
        return f"{self.user} muted match {self.match.id}"


# =============================================================================
# REPORT MODEL
# =============================================================================
class Report(models.Model):
    """
    Reports submitted by users for inappropriate content/behavior.
    Supports reporting users, groups, matches, and messages.
    """
    class ReportType(models.TextChoices):
        USER = 'user', 'User'
        GROUP = 'group', 'Group'
        MATCH = 'match', 'Match'
        MESSAGE = 'message', 'Message'

    class Reason(models.TextChoices):
        HARASSMENT = 'harassment', 'Harassment'
        SPAM = 'spam', 'Spam'
        INAPPROPRIATE = 'inappropriate', 'Inappropriate Content'
        FAKE = 'fake', 'Fake Profile'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        REVIEWED = 'reviewed', 'Reviewed'
        RESOLVED = 'resolved', 'Resolved'
        DISMISSED = 'dismissed', 'Dismissed'

    reporter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='submitted_reports'
    )
    report_type = models.CharField(max_length=20, choices=ReportType.choices)
    target_id = models.PositiveIntegerField(
        help_text="ID of the reported user/group/match/message"
    )
    reason = models.CharField(max_length=20, choices=Reason.choices)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_reports'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reports'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reporter', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['report_type', 'target_id']),
        ]

    def __str__(self):
        return f"Report by {self.reporter}: {self.report_type} #{self.target_id} ({self.reason})"


# =============================================================================
# SOLO MODE
# =============================================================================


class SoloMatch(models.Model):
    """
    Solo Mode match between two individual users.
    Tracks the lifecycle from swipe → match → coordination → blitz.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendiente'
        MATCHED = 'matched', 'Match mutuo'
        COORDINATING = 'coordinating', 'Coordinando'
        READY = 'ready', 'Listos'
        STARTED = 'started', 'Iniciado'
        EXPIRED = 'expired', 'Expirado'
        CANCELLED = 'cancelled', 'Cancelado'

    user_a = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='solo_matches_initiated',
    )
    user_b = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='solo_matches_received',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    blitz = models.ForeignKey(
        Blitz,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solo_matches',
    )
    chat = models.ForeignKey(
        'Chat',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solo_matches',
    )
    group = models.ForeignKey(
        'Group',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='solo_matches',
    )
    # Group creation confirmation (both must confirm before group is created)
    group_confirmed_a = models.BooleanField(default=False)
    group_confirmed_b = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'solo_matches'
        unique_together = ('user_a', 'user_b')
        indexes = [
            models.Index(fields=['user_a', 'status']),
            models.Index(fields=['user_b', 'status']),
            models.Index(fields=['status', 'expires_at']),
        ]

    def __str__(self):
        return f"SoloMatch: {self.user_a} → {self.user_b} ({self.status})"


class SoloCoordination(models.Model):
    """
    Real-time coordination state for a matched solo pair.
    Each user independently selects categories, time, and zone.
    """
    class Status(models.TextChoices):
        WAITING = 'waiting', 'Esperando'
        BOTH_READY = 'both_ready', 'Ambos listos'
        STARTED = 'started', 'Iniciado'
        EXPIRED = 'expired', 'Expirado'

    solo_match = models.OneToOneField(
        SoloMatch,
        on_delete=models.CASCADE,
        related_name='coordination',
    )
    user_a_categories = models.JSONField(default=list)
    user_a_time = models.JSONField(default=dict)
    user_a_zone = models.JSONField(default=dict)
    user_a_ready = models.BooleanField(default=False)

    user_b_categories = models.JSONField(default=list)
    user_b_time = models.JSONField(default=dict)
    user_b_zone = models.JSONField(default=dict)
    user_b_ready = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.WAITING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'solo_coordinations'

    def __str__(self):
        return f"SoloCoordination for SoloMatch {self.solo_match_id} ({self.status})"
