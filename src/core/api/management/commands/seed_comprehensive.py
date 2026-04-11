"""
Comprehensive seed data: ONE main user with ALL possible scenarios covered.

Creates 20 users, complete friendships, groups, blitz sessions, matches,
solo matches in every status, chats with messages, meetup plans, memories,
notifications, billing, reports, and more.

Usage:
    python manage.py seed_comprehensive
    python manage.py seed_comprehensive --main-uid HeWVSDyusKRmQGdtsNuuXSfGlQ43
    python manage.py seed_comprehensive --flush
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.utils import timezone

from api.models import (
    Blitz,
    BlitzInteraction,
    BlitzVote,
    Chat,
    Coupon,
    DeviceToken,
    Friendship,
    Group,
    GroupInvitation,
    GroupMembership,
    Invoice,
    InvoiceItem,
    Match,
    MatchActivity,
    MatchMute,
    MeetupPlan,
    Memory,
    MemoryPhoto,
    Message,
    Notification,
    Payment,
    PaymentMethod,
    Plan,
    PlanFeature,
    Profile,
    ProfilePhoto,
    Report,
    SoloCoordination,
    SoloMatch,
    Subscription,
    User,
    ZoneStats,
)
from api.Signals.signals import (
    notify_friend_request,
    notify_group_invitation,
    notify_group_liked,
    notify_group_member_joined,
    notify_match_created,
    notify_meetup_created,
    notify_meetup_status_changed,
    notify_new_message,
    notify_solo_match,
    notify_vote_needed,
)


def _set_dates(obj, **kwargs):
    """Override auto_now_add / auto_now fields via UPDATE."""
    if kwargs:
        type(obj).objects.filter(pk=obj.pk).update(**kwargs)


# ─── Avatar URLs (pravatar.cc) ────────────────────────────────────────
def _avatar(n):
    return f'https://i.pravatar.cc/400?img={n}'


class Command(BaseCommand):
    help = 'Seed comprehensive test data for all user scenarios'

    def add_arguments(self, parser):
        parser.add_argument(
            '--main-uid',
            default='seed_andrea_001',
            help='Firebase UID for the main user (default: seed_andrea_001)',
        )
        parser.add_argument(
            '--flush',
            action='store_true',
            help='Delete ALL existing data before seeding',
        )

    def handle(self, *args, **options):
        self.now = timezone.now()
        self.main_uid = options['main_uid']

        if options['flush']:
            self._flush()

        # Disconnect FCM notification signals to avoid noise during seeding
        self._disconnect_fcm_signals()

        try:
            with transaction.atomic():
                self._create_plans()
                self._create_users()
                self._create_profiles()
                self._create_profile_photos()
                self._create_friendships()
                self._create_groups()
                self._create_group_invitations()
                self._create_blitz_sessions()
                self._create_blitz_interactions()
                self._create_chats()
                self._create_matches()
                self._create_messages()
                self._create_match_activities()
                self._create_meetup_plans()
                self._create_memories()
                self._create_solo_matches()
                self._create_notifications()
                self._create_device_tokens()
                self._create_billing()
                self._create_reports()
                self._create_match_mutes()
        finally:
            self._reconnect_fcm_signals()

        self._print_summary()

    # ═══════════════════════════════════════════════════════════════════
    #  Signal management
    # ═══════════════════════════════════════════════════════════════════

    def _disconnect_fcm_signals(self):
        """Disconnect FCM push signals to avoid errors during seeding."""
        post_save.disconnect(notify_match_created, sender=Match)
        post_save.disconnect(notify_new_message, sender=Message)
        post_save.disconnect(notify_friend_request, sender=Friendship)
        post_save.disconnect(notify_group_liked, sender=BlitzInteraction)
        post_save.disconnect(notify_vote_needed, sender=BlitzInteraction)
        post_save.disconnect(notify_group_member_joined, sender=GroupMembership)
        post_save.disconnect(notify_meetup_created, sender=MeetupPlan)
        pre_save.disconnect(notify_meetup_status_changed, sender=MeetupPlan)
        post_save.disconnect(notify_group_invitation, sender=GroupInvitation)
        post_save.disconnect(notify_solo_match, sender=SoloMatch)
        self.stdout.write('  FCM signals disconnected')

    def _reconnect_fcm_signals(self):
        """Reconnect FCM push signals after seeding."""
        post_save.connect(notify_match_created, sender=Match)
        post_save.connect(notify_new_message, sender=Message)
        post_save.connect(notify_friend_request, sender=Friendship)
        post_save.connect(notify_group_liked, sender=BlitzInteraction)
        post_save.connect(notify_vote_needed, sender=BlitzInteraction)
        post_save.connect(notify_group_member_joined, sender=GroupMembership)
        post_save.connect(notify_meetup_created, sender=MeetupPlan)
        pre_save.connect(notify_meetup_status_changed, sender=MeetupPlan)
        post_save.connect(notify_group_invitation, sender=GroupInvitation)
        post_save.connect(notify_solo_match, sender=SoloMatch)
        self.stdout.write('  FCM signals reconnected')

    # ═══════════════════════════════════════════════════════════════════
    #  Flush
    # ═══════════════════════════════════════════════════════════════════

    def _flush(self):
        self.stdout.write(self.style.WARNING('\n⚠ Flushing all data...'))
        # Delete in reverse dependency order
        for model in [
            MemoryPhoto, Memory, MeetupPlan, MatchActivity, MatchMute,
            Message, BlitzVote, BlitzInteraction,
            SoloCoordination, SoloMatch, Match, Chat, Blitz,
            GroupInvitation, GroupMembership, Group,
            Friendship, Report, Notification, DeviceToken,
            ProfilePhoto, Profile,
            Payment, InvoiceItem, Invoice,
            Subscription, PaymentMethod, PlanFeature, Plan, Coupon,
            ZoneStats, User,
        ]:
            try:
                n = model.objects.all().delete()[0]
                if n:
                    self.stdout.write(f'  Deleted {n} {model.__name__}')
            except Exception:
                pass
        self.stdout.write(self.style.SUCCESS('  Flush complete\n'))

    # ═══════════════════════════════════════════════════════════════════
    #  1. Plans & Features
    # ═══════════════════════════════════════════════════════════════════

    def _create_plans(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Plans & Features ──'))

        self.free_plan, _ = Plan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Gratis',
                'plan_type': 'free',
                'price': Decimal('0.00'),
                'billing_interval': 'monthly',
                'is_active': True,
                'is_public': True,
                'display_order': 0,
            },
        )
        FREE_FEATURES = [
            ('max_groups', 'Grupos máximos', '3'),
            ('max_blitz_per_week', 'Blitz por semana', '3'),
            ('max_swipes_per_blitz', 'Swipes por Blitz', '10'),
            ('max_solo_connections', 'Conexiones Solo', '5'),
            ('advanced_filters', 'Filtros avanzados', 'false'),
            ('voice_chat', 'Chat de voz', 'false'),
            ('full_heat_map', 'Heat Map completo', 'false'),
            ('detailed_stats', 'Estadísticas detalladas', 'false'),
            ('priority_support', 'Soporte prioritario', 'false'),
            ('blur_notifications', 'Notificaciones difuminadas', 'true'),
        ]
        for key, name, value in FREE_FEATURES:
            PlanFeature.objects.update_or_create(
                plan=self.free_plan, feature_key=key,
                defaults={'feature_name': name, 'value': value},
            )

        self.premium_plan, _ = Plan.objects.get_or_create(
            slug='premium',
            defaults={
                'name': 'Premium',
                'plan_type': 'premium',
                'price': Decimal('0.99'),
                'billing_interval': 'monthly',
                'trial_days': 7,
                'is_active': True,
                'is_public': True,
                'display_order': 1,
            },
        )
        PREMIUM_FEATURES = [
            ('max_groups', 'Grupos máximos', 'unlimited'),
            ('max_blitz_per_week', 'Blitz por semana', 'unlimited'),
            ('max_swipes_per_blitz', 'Swipes por Blitz', 'unlimited'),
            ('max_solo_connections', 'Conexiones Solo', 'unlimited'),
            ('advanced_filters', 'Filtros avanzados', 'true'),
            ('voice_chat', 'Chat de voz', 'true'),
            ('full_heat_map', 'Heat Map completo', 'true'),
            ('detailed_stats', 'Estadísticas detalladas', 'true'),
            ('priority_support', 'Soporte prioritario', 'true'),
            ('blur_notifications', 'Notificaciones difuminadas', 'false'),
        ]
        for key, name, value in PREMIUM_FEATURES:
            PlanFeature.objects.update_or_create(
                plan=self.premium_plan, feature_key=key,
                defaults={'feature_name': name, 'value': value},
            )

        self.stdout.write(self.style.SUCCESS('  ✓ Free + Premium plans with 10 features each'))

    # ═══════════════════════════════════════════════════════════════════
    #  2. Users
    # ═══════════════════════════════════════════════════════════════════

    def _create_users(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Users (20) ──'))

        USER_DATA = [
            # (first, last, email, firebase_uid, avatar_num)
            ('Andrea', 'Salazar', 'andrea@squadup.test', self.main_uid, 22),
            ('Carlos', 'Mendoza', 'carlos@squadup.test', 'seed_carlos_002', 11),
            ('Mariana', 'López', 'mariana@squadup.test', 'seed_mariana_003', 32),
            ('Diego', 'Ramírez', 'diego@squadup.test', 'seed_diego_004', 12),
            ('Sofía', 'García', 'sofia@squadup.test', 'seed_sofia_005', 25),
            ('Javier', 'Torres', 'javier@squadup.test', 'seed_javier_006', 14),
            ('Valentina', 'Cruz', 'valentina@squadup.test', 'seed_valentina_007', 44),
            ('Mateo', 'Hernández', 'mateo@squadup.test', 'seed_mateo_008', 8),
            ('Camila', 'Ortiz', 'camila@squadup.test', 'seed_camila_009', 26),
            ('Sebastián', 'Flores', 'sebastian@squadup.test', 'seed_sebastian_010', 15),
            ('Isabella', 'Morales', 'isabella@squadup.test', 'seed_isabella_011', 45),
            ('Andrés', 'Silva', 'andres@squadup.test', 'seed_andres_012', 16),
            ('Luciana', 'Vargas', 'luciana@squadup.test', 'seed_luciana_013', 29),
            ('Emilio', 'Castillo', 'emilio@squadup.test', 'seed_emilio_014', 17),
            ('Renata', 'Aguilar', 'renata@squadup.test', 'seed_renata_015', 33),
            ('Santiago', 'Peña', 'santiago@squadup.test', 'seed_santiago_016', 18),
            ('Daniela', 'Ríos', 'daniela@squadup.test', 'seed_daniela_017', 34),
            ('Nicolás', 'Guzmán', 'nicolas@squadup.test', 'seed_nicolas_018', 19),
            ('Fernanda', 'Navarro', 'fernanda@squadup.test', 'seed_fernanda_019', 35),
            ('Pablo', 'Medina', 'pablo@squadup.test', 'seed_pablo_020', 20),
        ]

        self.users = []
        d30 = self.now - timedelta(days=30)

        for i, (first, last, email, uid, avatar) in enumerate(USER_DATA):
            user, created = User.objects.get_or_create(
                firebase_uid=uid,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                    'profile_photo': _avatar(avatar),
                    'is_verified': True,
                    'is_active': True,
                    'role': 'REGULAR',
                },
            )
            if created:
                _set_dates(user, created_at=d30 + timedelta(hours=i))
            self.users.append(user)

        # Convenience aliases
        (
            self.andrea, self.carlos, self.mariana, self.diego,
            self.sofia, self.javier, self.valentina, self.mateo,
            self.camila, self.sebastian, self.isabella, self.andres,
            self.luciana, self.emilio, self.renata, self.santiago,
            self.daniela, self.nicolas, self.fernanda, self.pablo,
        ) = self.users

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ {len(self.users)} users (main: {self.andrea.full_name}, uid={self.main_uid})'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  3. Profiles
    # ═══════════════════════════════════════════════════════════════════

    def _create_profiles(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Profiles ──'))

        PROFILE_DATA = [
            # (user, bio, interests, age, gender)
            (self.andrea, 'Aventurera y amante del café. Siempre buscando nuevas experiencias.', ['coffee', 'outdoors', 'music', 'travel', 'photography'], 24, 'Mujer'),
            (self.carlos, 'Gamer de corazón y deportista de fin de semana.', ['gaming', 'sports', 'drinks', 'party', 'music'], 22, 'Hombre'),
            (self.mariana, 'Foodie y viajera. Me encanta conocer gente nueva.', ['food', 'travel', 'coffee', 'art', 'chill'], 25, 'Mujer'),
            (self.diego, 'Estudiante de diseño. Fan de la fotografía callejera.', ['photography', 'art', 'coffee', 'music'], 23, 'Hombre'),
            (self.sofia, 'Corredora y amante de los perros.', ['sports', 'outdoors', 'chill', 'food'], 21, 'Mujer'),
            (self.javier, 'Desarrollador web. Café es mi gasolina.', ['gaming', 'coffee', 'music'], 26, 'Hombre'),
            (self.valentina, 'Artista digital y DJ los fines de semana.', ['art', 'music', 'party', 'drinks'], 23, 'Mujer'),
            (self.mateo, 'Chef en formación. Siempre probando recetas nuevas.', ['food', 'coffee', 'travel', 'chill'], 25, 'Hombre'),
            (self.camila, 'Psicóloga. Me encanta la música en vivo.', ['music', 'chill', 'art', 'coffee', 'outdoors'], 24, 'Mujer'),
            (self.sebastian, 'Surfista y fotógrafo de naturaleza.', ['sports', 'outdoors', 'photography', 'travel'], 27, 'Hombre'),
            (self.isabella, 'Bailarina y maestra de yoga.', ['sports', 'chill', 'music', 'art'], 22, 'Mujer'),
            (self.andres, 'Ingeniero civil. Fan del ciclismo.', ['sports', 'outdoors', 'coffee'], 28, 'Hombre'),
            (self.luciana, 'Diseñadora de modas. Fashionista por naturaleza.', ['art', 'party', 'drinks', 'travel'], 24, 'Mujer'),
            (self.emilio, 'Emprendedor tech. Weekend warrior por excelencia.', ['gaming', 'sports', 'food', 'drinks'], 26, 'Hombre'),
            (self.renata, 'Bióloga marina. Amante del océano.', ['outdoors', 'travel', 'photography', 'chill'], 25, 'Mujer'),
            (self.santiago, 'Músico y productor. Siempre en busca del ritmo.', ['music', 'party', 'drinks', 'art'], 27, 'Hombre'),
            (self.daniela, 'Periodista. Curiosa por naturaleza.', ['travel', 'food', 'coffee', 'art', 'photography'], 23, 'Mujer'),
            (self.nicolas, 'Arquitecto. Los detalles importan.', ['art', 'coffee', 'outdoors', 'photography'], 29, 'Hombre'),
            (self.fernanda, 'Veterinaria. 3 gatos, 1 perro.', ['chill', 'coffee', 'food', 'outdoors'], 22, 'Mujer'),
            (self.pablo, 'Foodie profesional. Conoce cada taquería de TJ.', ['food', 'drinks', 'coffee', 'music', 'chill'], 24, 'Hombre'),
        ]

        tj_location = {'lat': 32.5149, 'lng': -117.0382, 'city': 'Tijuana, BC'}

        for user, bio, interests, age, gender in PROFILE_DATA:
            Profile.objects.update_or_create(
                user=user,
                defaults={
                    'bio': bio,
                    'interests': interests,
                    'age': age,
                    'gender': gender,
                    'default_location': tj_location,
                },
            )

        self.stdout.write(self.style.SUCCESS(f'  ✓ {len(PROFILE_DATA)} profiles'))

    # ═══════════════════════════════════════════════════════════════════
    #  4. Profile Photos (gallery)
    # ═══════════════════════════════════════════════════════════════════

    def _create_profile_photos(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Profile Photos ──'))
        count = 0

        # Main user gets 4 gallery photos
        for i in range(4):
            _, created = ProfilePhoto.objects.get_or_create(
                user=self.andrea,
                order=i,
                defaults={
                    'image_url': f'https://picsum.photos/seed/andrea{i}/400/400',
                    'caption': ['En la playa', 'Con amigos', 'Café favorito', 'Explorando'][i],
                },
            )
            if created:
                count += 1

        # Some supporting users get 1-2 photos
        for user, n in [(self.carlos, 2), (self.mariana, 2), (self.mateo, 1),
                        (self.santiago, 1), (self.camila, 1)]:
            for i in range(n):
                _, created = ProfilePhoto.objects.get_or_create(
                    user=user,
                    order=i,
                    defaults={
                        'image_url': f'https://picsum.photos/seed/{user.first_name.lower()}{i}/400/400',
                    },
                )
                if created:
                    count += 1

        self.stdout.write(self.style.SUCCESS(f'  ✓ {count} gallery photos'))

    # ═══════════════════════════════════════════════════════════════════
    #  5. Friendships
    # ═══════════════════════════════════════════════════════════════════

    def _create_friendships(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Friendships ──'))

        FRIENDSHIPS = [
            # (from, to, status, days_ago, source)
            (self.andrea, self.carlos, 'accepted', 25, 'direct'),    # Mutual friend
            (self.andrea, self.mariana, 'accepted', 24, 'direct'),   # Mutual friend
            (self.andrea, self.diego, 'pending', 3, 'direct'),       # Sent by Andrea, pending
            (self.sofia, self.andrea, 'pending', 2, 'direct'),       # Received by Andrea, pending
            (self.andrea, self.javier, 'rejected', 20, 'direct'),    # Rejected
            (self.andrea, self.valentina, 'blocked', 15, 'direct'),  # Blocked
            # Extra accepted friendships for group creation
            (self.andrea, self.emilio, 'accepted', 20, 'direct'),
            (self.andrea, self.renata, 'accepted', 20, 'direct'),
            (self.carlos, self.mariana, 'accepted', 22, 'direct'),
            (self.emilio, self.renata, 'accepted', 22, 'direct'),
            (self.santiago, self.daniela, 'accepted', 22, 'direct'),
            # Solo mode mutual friendships (needed for quick_duo)
            (self.andrea, self.mateo, 'accepted', 10, 'solo'),
            (self.andrea, self.camila, 'accepted', 10, 'solo'),
            (self.andrea, self.fernanda, 'accepted', 10, 'solo'),
            (self.andrea, self.nicolas, 'accepted', 10, 'solo'),
        ]

        count = 0
        for user_from, user_to, status, days_ago, source in FRIENDSHIPS:
            f, created = Friendship.objects.get_or_create(
                user_from=user_from,
                user_to=user_to,
                defaults={'status': status, 'source': source},
            )
            if created:
                ts = self.now - timedelta(days=days_ago)
                _set_dates(f, created_at=ts, updated_at=ts)
                count += 1

        self.stdout.write(self.style.SUCCESS(f'  ✓ {count} friendships'))

    # ═══════════════════════════════════════════════════════════════════
    #  6. Groups & Memberships
    # ═══════════════════════════════════════════════════════════════════

    def _create_groups(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Groups & Memberships ──'))

        d20 = self.now - timedelta(days=20)
        d18 = self.now - timedelta(days=18)

        # Group 1: Los Aventureros (Andrea = creator + admin)
        self.grp_aventureros, _ = Group.objects.get_or_create(
            name='Los Aventureros',
            defaults={
                'description': 'Explorando Tijuana un fin de semana a la vez.',
                'creator': self.andrea,
                'image_url': 'https://picsum.photos/seed/aventureros/200/200',
            },
        )
        _set_dates(self.grp_aventureros, created_at=d20)
        for user, role in [(self.andrea, 'admin'), (self.carlos, 'member'), (self.mariana, 'member')]:
            gm, _ = GroupMembership.objects.get_or_create(
                user=user, group=self.grp_aventureros, defaults={'role': role},
            )

        # Group 2: Weekend Warriors (Emilio = admin, Andrea = member)
        self.grp_warriors, _ = Group.objects.get_or_create(
            name='Weekend Warriors',
            defaults={
                'description': 'Para los que viven para el fin de semana.',
                'creator': self.emilio,
                'image_url': 'https://picsum.photos/seed/warriors/200/200',
            },
        )
        _set_dates(self.grp_warriors, created_at=d18)
        for user, role in [(self.emilio, 'admin'), (self.renata, 'member'), (self.andrea, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_warriors, defaults={'role': role},
            )

        # Group 3: Squad Tijuana (opponent group for matches)
        self.grp_tijuana, _ = Group.objects.get_or_create(
            name='Squad Tijuana',
            defaults={
                'description': 'Los originales de TJ.',
                'creator': self.santiago,
                'image_url': 'https://picsum.photos/seed/squadtj/200/200',
            },
        )
        _set_dates(self.grp_tijuana, created_at=d18)
        for user, role in [(self.santiago, 'admin'), (self.daniela, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_tijuana, defaults={'role': role},
            )

        # Group 4: Night Owls (Carlos = admin, invitation pending for Andrea)
        self.grp_owls, _ = Group.objects.get_or_create(
            name='Night Owls',
            defaults={
                'description': 'La noche es joven.',
                'creator': self.carlos,
            },
        )
        for user, role in [(self.carlos, 'admin'), (self.mariana, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_owls, defaults={'role': role},
            )

        # Group 5: Foodies TJ (discoverable opponent)
        self.grp_foodies, _ = Group.objects.get_or_create(
            name='Foodies TJ',
            defaults={
                'description': 'Si no es con hambre, no es plan.',
                'creator': self.pablo,
            },
        )
        for user, role in [(self.pablo, 'admin'), (self.diego, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_foodies, defaults={'role': role},
            )

        # Group 6: Solo Mode duo (Andrea & Santiago)
        self.grp_solo_duo, _ = Group.objects.get_or_create(
            name='You & Santiago',
            defaults={
                'description': 'Solo Mode duo for Coffee',
                'creator': self.andrea,
                'metadata': {'source': 'solo'},
            },
        )
        for user, role in [(self.andrea, 'admin'), (self.santiago, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_solo_duo, defaults={'role': role},
            )

        self.stdout.write(self.style.SUCCESS('  ✓ 6 groups with memberships'))

    # ═══════════════════════════════════════════════════════════════════
    #  7. Group Invitations
    # ═══════════════════════════════════════════════════════════════════

    def _create_group_invitations(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Group Invitations ──'))

        # Pending invitation to Night Owls
        GroupInvitation.objects.get_or_create(
            group=self.grp_owls,
            inviter=self.carlos,
            invitee=self.andrea,
            defaults={'status': 'pending'},
        )

        # Historical: accepted invitation to Weekend Warriors
        inv, created = GroupInvitation.objects.get_or_create(
            group=self.grp_warriors,
            inviter=self.emilio,
            invitee=self.andrea,
            defaults={
                'status': 'accepted',
                'responded_at': self.now - timedelta(days=18),
            },
        )
        if created:
            _set_dates(inv, created_at=self.now - timedelta(days=19))

        # Declined invitation
        GroupInvitation.objects.get_or_create(
            group=self.grp_foodies,
            inviter=self.pablo,
            invitee=self.andrea,
            defaults={
                'status': 'declined',
                'responded_at': self.now - timedelta(days=10),
            },
        )

        self.stdout.write(self.style.SUCCESS('  ✓ 3 group invitations (pending + accepted + declined)'))

    # ═══════════════════════════════════════════════════════════════════
    #  8. Blitz Sessions
    # ═══════════════════════════════════════════════════════════════════

    def _create_blitz_sessions(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Blitz Sessions ──'))

        tj_loc = {'lat': 32.5149, 'lng': -117.0382, 'address': 'Tijuana, BC', 'radius_km': 5}

        # 1. ACTIVE: Los Aventureros, democratic, 45 min remaining
        self.blitz_active, _ = Blitz.objects.get_or_create(
            group=self.grp_aventureros,
            leader=self.andrea,
            status='active',
            swipe_mode='democratic',
            defaults={
                'location': tj_loc,
                'activity_type': 'coffee',
                'min_opponent_size': 2,
                'max_opponent_size': 5,
                'expires_at': self.now + timedelta(minutes=45),
                'metadata': {'activities': ['coffee', 'food', 'chill']},
            },
        )

        # 2. MATCHED: Los Aventureros (matched with Squad Tijuana, 14 days ago)
        self.blitz_matched_a, _ = Blitz.objects.get_or_create(
            group=self.grp_aventureros,
            leader=self.andrea,
            status='matched',
            activity_type='outdoors',
            defaults={
                'location': tj_loc,
                'swipe_mode': 'leader',
                'expires_at': self.now - timedelta(days=14, hours=-1),
            },
        )
        _set_dates(self.blitz_matched_a,
                   started_at=self.now - timedelta(days=14),
                   created_at=self.now - timedelta(days=14))

        # 3. EXPIRED: Los Aventureros (5 days ago)
        self.blitz_expired, _ = Blitz.objects.get_or_create(
            group=self.grp_aventureros,
            leader=self.carlos,
            status='expired',
            activity_type='sports',
            defaults={
                'location': tj_loc,
                'expires_at': self.now - timedelta(days=5),
            },
        )
        _set_dates(self.blitz_expired,
                   started_at=self.now - timedelta(days=5, hours=1),
                   created_at=self.now - timedelta(days=5, hours=1))

        # 4. CANCELLED: Weekend Warriors (3 days ago)
        self.blitz_cancelled, _ = Blitz.objects.get_or_create(
            group=self.grp_warriors,
            leader=self.emilio,
            status='cancelled',
            activity_type='party',
            defaults={
                'location': tj_loc,
                'expires_at': self.now - timedelta(days=3),
            },
        )
        _set_dates(self.blitz_cancelled,
                   started_at=self.now - timedelta(days=3, hours=1),
                   created_at=self.now - timedelta(days=3, hours=1))

        # 5. MATCHED: Squad Tijuana (paired with #2, 14 days ago)
        self.blitz_matched_b, _ = Blitz.objects.get_or_create(
            group=self.grp_tijuana,
            leader=self.santiago,
            status='matched',
            activity_type='music',
            defaults={
                'location': tj_loc,
                'swipe_mode': 'leader',
                'expires_at': self.now - timedelta(days=14, hours=-1),
            },
        )
        _set_dates(self.blitz_matched_b,
                   started_at=self.now - timedelta(days=14),
                   created_at=self.now - timedelta(days=14))

        # 6. ACTIVE: Squad Tijuana (discoverable, pending like from Andrea)
        self.blitz_disco_tj, _ = Blitz.objects.get_or_create(
            group=self.grp_tijuana,
            leader=self.santiago,
            status='active',
            activity_type='drinks',
            defaults={
                'location': tj_loc,
                'min_opponent_size': 2,
                'expires_at': self.now + timedelta(minutes=30),
            },
        )

        # 7. ACTIVE: Foodies TJ (discoverable, liked Andrea's active blitz)
        self.blitz_disco_food, _ = Blitz.objects.get_or_create(
            group=self.grp_foodies,
            leader=self.pablo,
            status='active',
            activity_type='food',
            defaults={
                'location': tj_loc,
                'min_opponent_size': 2,
                'expires_at': self.now + timedelta(minutes=50),
            },
        )

        self.stdout.write(self.style.SUCCESS(
            '  ✓ 7 blitz sessions (1 active, 2 matched, 1 expired, 1 cancelled, 2 discoverable)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  9. Blitz Interactions & Votes
    # ═══════════════════════════════════════════════════════════════════

    def _create_blitz_interactions(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Blitz Interactions & Votes ──'))

        # Normalize blitz order (blitz_1.id < blitz_2.id) for matched pair
        b_a = self.blitz_matched_a
        b_b = self.blitz_matched_b

        # Mutual likes that led to the group match (14 days ago)
        int1, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=b_a, to_blitz=b_b,
            defaults={'interaction_type': 'like'},
        )
        _set_dates(int1, created_at=self.now - timedelta(days=14))

        int2, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=b_b, to_blitz=b_a,
            defaults={'interaction_type': 'like'},
        )
        _set_dates(int2, created_at=self.now - timedelta(days=14))

        # Active: Andrea's group liked Squad Tijuana's active blitz (democratic, needs consensus)
        int3, created = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_active, to_blitz=self.blitz_disco_tj,
            defaults={'interaction_type': 'like', 'requires_consensus': True},
        )
        if created:
            # Create votes for democratic consensus
            BlitzVote.objects.get_or_create(
                interaction=int3, user=self.andrea,
                defaults={'vote': 'approved', 'voted_at': self.now},
            )
            BlitzVote.objects.get_or_create(
                interaction=int3, user=self.carlos,
                defaults={'vote': 'approved', 'voted_at': self.now - timedelta(minutes=5)},
            )
            BlitzVote.objects.get_or_create(
                interaction=int3, user=self.mariana,
                defaults={'vote': 'pending'},
            )

        # Received: Foodies liked Andrea's active blitz
        int4, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_disco_food, to_blitz=self.blitz_active,
            defaults={'interaction_type': 'like'},
        )

        self.stdout.write(self.style.SUCCESS(
            '  ✓ 4 interactions (2 mutual match, 1 democratic pending, 1 received like) + 3 votes'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  10. Chats
    # ═══════════════════════════════════════════════════════════════════

    def _create_chats(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Chats ──'))

        # Chat 1: Group match (Los Aventureros ↔ Squad Tijuana)
        self.chat_match = Chat.objects.create(
            is_active=True,
            last_message_at=self.now - timedelta(hours=2),
            last_message_preview='Perfecto, nos vemos ahí',
        )
        self.chat_match.participants.add(
            self.andrea, self.carlos, self.mariana, self.santiago, self.daniela,
        )
        _set_dates(self.chat_match, created_at=self.now - timedelta(days=14))

        # Chat 2: Solo match Andrea ↔ Mateo (matched)
        self.chat_solo_mateo = Chat.objects.create(
            is_active=True,
            metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=6),
            last_message_preview='¿Qué te gusta hacer los fines?',
        )
        self.chat_solo_mateo.participants.add(self.andrea, self.mateo)
        _set_dates(self.chat_solo_mateo, created_at=self.now - timedelta(days=7))

        # Chat 3: Solo match Andrea ↔ Camila (coordinating)
        self.chat_solo_camila = Chat.objects.create(
            is_active=True,
            metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=12),
            last_message_preview='¡Coordinemos!',
        )
        self.chat_solo_camila.participants.add(self.andrea, self.camila)
        _set_dates(self.chat_solo_camila, created_at=self.now - timedelta(days=5))

        # Chat 4: Solo match Andrea ↔ Fernanda (ready)
        self.chat_solo_fernanda = Chat.objects.create(
            is_active=True,
            metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=3),
            last_message_preview='¡Lista!',
        )
        self.chat_solo_fernanda.participants.add(self.andrea, self.fernanda)
        _set_dates(self.chat_solo_fernanda, created_at=self.now - timedelta(days=4))

        # Chat 5: Solo match Andrea ↔ Nicolás (started)
        self.chat_solo_nicolas = Chat.objects.create(
            is_active=True,
            metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=1),
            last_message_preview='¡Vamos!',
        )
        self.chat_solo_nicolas.participants.add(self.andrea, self.nicolas)
        _set_dates(self.chat_solo_nicolas, created_at=self.now - timedelta(days=3))

        self.stdout.write(self.style.SUCCESS('  ✓ 5 chats (1 group match + 4 solo)'))

    # ═══════════════════════════════════════════════════════════════════
    #  11. Matches
    # ═══════════════════════════════════════════════════════════════════

    def _create_matches(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Matches ──'))

        # Ensure blitz_1.id < blitz_2.id (convention from confirm_match)
        b1, b2 = sorted(
            [self.blitz_matched_a, self.blitz_matched_b], key=lambda b: b.id,
        )

        # Main active match: Los Aventureros ↔ Squad Tijuana
        self.match_active, _ = Match.objects.get_or_create(
            blitz_1=b1,
            blitz_2=b2,
            defaults={
                'status': 'active',
                'matched_at': self.now - timedelta(days=14),
                'chat': self.chat_match,
            },
        )
        _set_dates(self.match_active, created_at=self.now - timedelta(days=14))

        self.stdout.write(self.style.SUCCESS('  ✓ 1 active match (Los Aventureros ↔ Squad Tijuana)'))

    # ═══════════════════════════════════════════════════════════════════
    #  12. Messages
    # ═══════════════════════════════════════════════════════════════════

    def _create_messages(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Messages ──'))
        count = 0

        # ── Chat 1: Group match (all read) ──
        msgs_match = [
            (None, 'system', '¡Match creado! Los Aventureros y Squad Tijuana.', -14 * 24),
            (self.andrea, 'text', '¡Hola! ¿Qué onda, qué planes tienen?', -14 * 24 + 1),
            (self.santiago, 'text', 'Hey! Estamos buscando algo chill este fin de semana.', -14 * 24 + 2),
            (self.daniela, 'text', '¡Hola a todos! 👋', -14 * 24 + 3),
            (self.carlos, 'text', 'Nosotros igual, ¿conocen algún lugar nuevo?', -13 * 24),
            (self.andrea, 'text', 'Perfecto, nos vemos ahí', -2),
        ]
        for sender, msg_type, text, hours_ago in msgs_match:
            m = Message.objects.create(
                chat=self.chat_match,
                sender=sender,
                text=text,
                message_type=msg_type,
                is_read=True,
                read_at=self.now - timedelta(hours=max(0, hours_ago - 1)),
            )
            _set_dates(m, created_at=self.now + timedelta(hours=hours_ago))
            count += 1

        # ── Chat 2: Solo Mateo (last 2 unread for Andrea) ──
        msgs_mateo = [
            (None, 'system', '¡Conexión mutua! 🎉', -7 * 24),
            (self.andrea, 'text', '¡Hola Mateo! 👋', -7 * 24 + 1, True),
            (self.mateo, 'text', 'Hey Andrea! Me da gusto conectar.', -6, False),
            (self.mateo, 'text', '¿Qué te gusta hacer los fines de semana?', -6, False),
        ]
        for entry in msgs_mateo:
            sender, msg_type, text, hours_ago = entry[:4]
            is_read = entry[4] if len(entry) > 4 else True
            m = Message.objects.create(
                chat=self.chat_solo_mateo,
                sender=sender,
                text=text,
                message_type=msg_type,
                is_read=is_read,
            )
            _set_dates(m, created_at=self.now + timedelta(hours=hours_ago))
            count += 1

        # ── Chat 3: Solo Camila (short exchange) ──
        for sender, text, hours_ago in [
            (None, '¡Conexión mutua! 🎉', -5 * 24),
            (self.camila, '¡Hola Andrea! ¿Coordinamos?', -12),
        ]:
            m = Message.objects.create(
                chat=self.chat_solo_camila, sender=sender,
                text=text, message_type='system' if sender is None else 'text',
                is_read=True,
            )
            _set_dates(m, created_at=self.now + timedelta(hours=hours_ago))
            count += 1

        # ── Chat 4: Solo Fernanda ──
        m = Message.objects.create(
            chat=self.chat_solo_fernanda, sender=None,
            text='¡Conexión mutua! 🎉', message_type='system', is_read=True,
        )
        _set_dates(m, created_at=self.now - timedelta(days=4))
        count += 1

        # ── Chat 5: Solo Nicolás (blitz started) ──
        for sender, text, hours_ago in [
            (None, '¡Blitz iniciado! 🚀', -3 * 24),
            (self.nicolas, '¡Listo para la aventura!', -3 * 24 + 1),
            (self.andrea, '¡Vamos!', -1),
        ]:
            m = Message.objects.create(
                chat=self.chat_solo_nicolas, sender=sender,
                text=text, message_type='system' if sender is None else 'text',
                is_read=True,
            )
            _set_dates(m, created_at=self.now + timedelta(hours=hours_ago))
            count += 1

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ {count} messages (6 group chat + 4 solo Mateo + 2 Camila + 1 Fernanda + 3 Nicolás)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  13. Match Activities
    # ═══════════════════════════════════════════════════════════════════

    def _create_match_activities(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Match Activities ──'))

        ACTIVITIES = [
            ('match_created', self.andrea, 'Match creado entre Los Aventureros y Squad Tijuana', -14),
            ('chat_started', self.andrea, 'Chat iniciado', -14),
            ('plan_suggested', self.santiago, 'Santiago propuso Bowling night', -10),
            ('plan_accepted', self.andrea, 'Plan aceptado por Andrea', -9),
            ('meetup_confirmed', self.santiago, 'Encuentro confirmado', -8),
            ('meetup_completed', self.andrea, 'Encuentro completado', -8),
            ('memory_added', self.andrea, 'Nuevo recuerdo: Bowling night', -7),
            ('photo_shared', self.daniela, 'Daniela compartió una foto', -7),
        ]

        for activity_type, triggered_by, desc, days_ago in ACTIVITIES:
            ma = MatchActivity.objects.create(
                match=self.match_active,
                activity_type=activity_type,
                triggered_by=triggered_by,
                description=desc,
            )
            _set_dates(ma, created_at=self.now + timedelta(days=days_ago))

        self.stdout.write(self.style.SUCCESS(f'  ✓ {len(ACTIVITIES)} match activities'))

    # ═══════════════════════════════════════════════════════════════════
    #  14. Meetup Plans
    # ═══════════════════════════════════════════════════════════════════

    def _create_meetup_plans(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Meetup Plans ──'))

        PLANS = [
            # (title, status, proposed_by, scheduled_offset_days, location_name)
            ('Café en Plaza Río', 'proposed', self.andrea, 5,
             'Plaza Río Tijuana', 'Paseo de los Héroes 9350'),
            ('Cena en Foodgarden', 'accepted', self.santiago, 7,
             'Foodgarden TJ', 'Blvd. Agua Caliente 4558'),
            ('Chill en el parque', 'confirmed', self.andrea, 3,
             'Parque Morelos', 'Av. de los Insurgentes s/n'),
            ('Bowling night', 'completed', self.santiago, -8,
             'Bol Revolución', 'Av. Revolución 1234'),
            ('Playa Rosarito', 'cancelled', self.andrea, -5,
             'Playa Rosarito', 'Blvd. Benito Juárez'),
        ]

        for title, status, proposed_by, sched_days, loc_name, loc_addr in PLANS:
            mp = MeetupPlan.objects.create(
                match=self.match_active,
                proposed_by=proposed_by,
                title=title,
                scheduled_at=self.now + timedelta(days=sched_days),
                location_name=loc_name,
                location_address=loc_addr,
                location_coords={
                    'lat': 32.5149 + random.uniform(-0.02, 0.02),
                    'lng': -117.0382 + random.uniform(-0.02, 0.02),
                },
                status=status,
            )
            _set_dates(mp,
                       created_at=self.now + timedelta(days=min(sched_days, 0) - 2))

        self.stdout.write(self.style.SUCCESS(
            '  ✓ 5 meetup plans (proposed, accepted, confirmed, completed, cancelled)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  15. Memories & Photos
    # ═══════════════════════════════════════════════════════════════════

    def _create_memories(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Memories ──'))

        # Memory 1: Outing with photos
        mem1 = Memory.objects.create(
            match=self.match_active,
            created_by=self.andrea,
            memory_type='outing',
            title='Bowling night con Squad Tijuana',
            event_date=(self.now - timedelta(days=8)).date(),
            notes='Increíble noche de boliche. Santiago es imposible de ganarle.',
            location_name='Bol Revolución',
        )
        _set_dates(mem1, created_at=self.now - timedelta(days=7))
        MemoryPhoto.objects.create(
            memory=mem1, uploaded_by=self.andrea, order=0,
            image_url='https://picsum.photos/seed/bowling1/600/400',
            caption='¡Strike!',
        )
        MemoryPhoto.objects.create(
            memory=mem1, uploaded_by=self.daniela, order=1,
            image_url='https://picsum.photos/seed/bowling2/600/400',
            caption='El equipo completo',
        )

        # Memory 2: Photo type
        mem2 = Memory.objects.create(
            match=self.match_active,
            created_by=self.santiago,
            memory_type='photo',
            title='Foto grupal en Plaza Río',
            event_date=(self.now - timedelta(days=6)).date(),
            notes='',
        )
        _set_dates(mem2, created_at=self.now - timedelta(days=6))
        MemoryPhoto.objects.create(
            memory=mem2, uploaded_by=self.santiago, order=0,
            image_url='https://picsum.photos/seed/grupofoto/600/400',
            caption='Todos juntos',
        )

        # Memory 3: Note type (no photos)
        mem3 = Memory.objects.create(
            match=self.match_active,
            created_by=self.andrea,
            memory_type='note',
            title='Ideas para el próximo encuentro',
            event_date=(self.now - timedelta(days=5)).date(),
            notes='Opciones: playa, museo de cera, escape room. Todos votan por escape room.',
        )
        _set_dates(mem3, created_at=self.now - timedelta(days=5))

        self.stdout.write(self.style.SUCCESS(
            '  ✓ 3 memories (outing+2photos, photo+1photo, note) + 3 photos'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  16. Solo Matches & Coordinations
    # ═══════════════════════════════════════════════════════════════════

    def _create_solo_matches(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Solo Matches (8 statuses) ──'))

        # 1. PENDING (sent by Andrea)
        sm_pending_sent, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.sebastian,
            defaults={
                'status': 'pending',
                'expires_at': self.now + timedelta(hours=20),
            },
        )
        _set_dates(sm_pending_sent, created_at=self.now - timedelta(hours=4))

        # 2. PENDING (received by Andrea)
        sm_pending_recv, _ = SoloMatch.objects.get_or_create(
            user_a=self.isabella, user_b=self.andrea,
            defaults={
                'status': 'pending',
                'expires_at': self.now + timedelta(hours=18),
            },
        )
        _set_dates(sm_pending_recv, created_at=self.now - timedelta(hours=6))

        # 3. MATCHED (Andrea ↔ Mateo, with chat, coordination=waiting)
        sm_matched, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.mateo,
            defaults={
                'status': 'matched',
                'matched_at': self.now - timedelta(days=7),
                'expires_at': self.now + timedelta(days=3),
                'chat': self.chat_solo_mateo,
            },
        )
        _set_dates(sm_matched, created_at=self.now - timedelta(days=7))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_matched,
            defaults={
                'status': 'waiting',
                'user_a_categories': ['coffee', 'food'],
                'expires_at': self.now + timedelta(days=3),
            },
        )

        # 4. COORDINATING (Andrea ↔ Camila, both have preferences)
        sm_coordinating, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.camila,
            defaults={
                'status': 'coordinating',
                'matched_at': self.now - timedelta(days=5),
                'expires_at': self.now + timedelta(days=2),
                'chat': self.chat_solo_camila,
            },
        )
        _set_dates(sm_coordinating, created_at=self.now - timedelta(days=5))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_coordinating,
            defaults={
                'status': 'waiting',
                'user_a_categories': ['music', 'coffee', 'chill'],
                'user_a_time': {'date': '2026-02-22', 'start_time': '18:00', 'end_time': '21:00'},
                'user_a_zone': {'name': 'Zona Río'},
                'user_b_categories': ['music', 'art', 'coffee'],
                'user_b_time': {'date': '2026-02-22', 'start_time': '19:00', 'end_time': '22:00'},
                'user_b_zone': {'name': 'La Cacho'},
                'expires_at': self.now + timedelta(days=2),
            },
        )

        # 5. READY (Andrea ↔ Fernanda, both ready)
        sm_ready, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.fernanda,
            defaults={
                'status': 'ready',
                'matched_at': self.now - timedelta(days=4),
                'expires_at': self.now + timedelta(days=1),
                'chat': self.chat_solo_fernanda,
            },
        )
        _set_dates(sm_ready, created_at=self.now - timedelta(days=4))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_ready,
            defaults={
                'status': 'both_ready',
                'user_a_categories': ['coffee', 'outdoors', 'food'],
                'user_a_time': {'date': '2026-02-21', 'start_time': '10:00', 'end_time': '13:00'},
                'user_a_zone': {'name': 'Playas de Tijuana'},
                'user_a_ready': True,
                'user_b_categories': ['coffee', 'chill', 'food'],
                'user_b_time': {'date': '2026-02-21', 'start_time': '10:00', 'end_time': '14:00'},
                'user_b_zone': {'name': 'Playas de Tijuana'},
                'user_b_ready': True,
                'expires_at': self.now + timedelta(days=1),
            },
        )

        # 6. STARTED (Andrea ↔ Nicolás, with duo group + blitz)
        # Create duo group
        self.grp_duo_nicolas, _ = Group.objects.get_or_create(
            name='Andrea & Nicolás',
            defaults={
                'description': 'Duo de Solo Mode',
                'creator': self.andrea,
            },
        )
        for user, role in [(self.andrea, 'admin'), (self.nicolas, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_duo_nicolas, defaults={'role': role},
            )

        # Create blitz for started solo match
        tj_loc = {'lat': 32.5149, 'lng': -117.0382, 'address': 'Tijuana, BC', 'radius_km': 5}
        self.blitz_solo_started, _ = Blitz.objects.get_or_create(
            group=self.grp_duo_nicolas,
            leader=self.andrea,
            status='active',
            activity_type='coffee',
            defaults={
                'location': tj_loc,
                'expires_at': self.now + timedelta(minutes=25),
                'metadata': {'activities': ['coffee', 'outdoors', 'art']},
            },
        )

        sm_started, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.nicolas,
            defaults={
                'status': 'started',
                'matched_at': self.now - timedelta(days=3),
                'chat': self.chat_solo_nicolas,
                'group': self.grp_duo_nicolas,
                'blitz': self.blitz_solo_started,
                'group_confirmed_a': True,
                'group_confirmed_b': True,
            },
        )
        _set_dates(sm_started, created_at=self.now - timedelta(days=3))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_started,
            defaults={
                'status': 'started',
                'user_a_categories': ['coffee', 'outdoors'],
                'user_a_ready': True,
                'user_b_categories': ['art', 'coffee'],
                'user_b_ready': True,
            },
        )

        # 7. EXPIRED (Andrea ↔ Andrés)
        sm_expired, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.andres,
            defaults={
                'status': 'expired',
                'matched_at': self.now - timedelta(days=15),
                'expires_at': self.now - timedelta(days=8),
            },
        )
        _set_dates(sm_expired, created_at=self.now - timedelta(days=15))

        # 8. CANCELLED (Andrea ↔ Luciana)
        sm_cancelled, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.luciana,
            defaults={
                'status': 'cancelled',
                'matched_at': self.now - timedelta(days=12),
                'expires_at': self.now - timedelta(days=5),
            },
        )
        _set_dates(sm_cancelled, created_at=self.now - timedelta(days=12))

        self.stdout.write(self.style.SUCCESS(
            '  ✓ 8 solo matches (pending×2, matched, coordinating, ready, started, expired, cancelled)\n'
            '  ✓ 4 solo coordinations (waiting, waiting+prefs, both_ready, started)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  17. Notifications (all 13 types)
    # ═══════════════════════════════════════════════════════════════════

    def _create_notifications(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Notifications ──'))

        NOTIFS = [
            # (type, title, body, is_read, days_ago, data)
            ('system', '¡Bienvenida a SquadUp!',
             'Tu cuenta está lista. Completa tu perfil para empezar.', True, 30, {}),
            ('friend_request', 'Nueva solicitud de amistad',
             'Sofía García quiere ser tu amiga.', False, 2,
             {'sender_id': self.sofia.id}),
            ('group_invite', 'Invitación a grupo',
             'Carlos te invitó a Night Owls.', False, 4,
             {'sender_id': self.carlos.id, 'group_id': self.grp_owls.id}),
            ('blitz_match', '¡Es un Match! 🎉',
             'Los Aventureros y Squad Tijuana hicieron match.', True, 14,
             {'match_id': getattr(self, 'match_active', None) and self.match_active.id}),
            ('blitz_like', '¡Un grupo le dio like a Los Aventureros!',
             'Foodies TJ está interesado en tu grupo.', False, 0,
             {'blitz_id': getattr(self, 'blitz_active', None) and self.blitz_active.id}),
            ('blitz_vote_request', 'Voto necesario',
             'Andrea propuso dar like a Squad Tijuana. ¡Vota!', True, 0,
             {}),
            ('blitz_expiring', '⏰ Tu Blitz está por expirar',
             'Los Aventureros tiene 15 minutos restantes.', False, 0,
             {'blitz_id': getattr(self, 'blitz_active', None) and self.blitz_active.id}),
            ('new_message', 'Nuevo mensaje',
             'Mateo: ¿Qué te gusta hacer los fines de semana?', False, 0,
             {'sender_id': self.mateo.id}),
            ('solo_connection', 'Nueva conexión',
             'Isabella quiere conectar contigo.', False, 0,
             {'sender_id': self.isabella.id}),
            ('solo_match', '⚡ ¡Es un Match!',
             'Tú y Mateo quieren conectar. ¡Coordinen su encuentro!', True, 7,
             {'sender_id': self.mateo.id}),
            ('meetup_proposed', '📍 Nuevo plan propuesto',
             'Santiago propuso: Bowling night.', True, 10,
             {'sender_id': self.santiago.id}),
            ('meetup_confirmed', '✅ Plan confirmado',
             'Chill en el parque está confirmado.', True, 8, {}),
            ('memory_added', '📸 Nuevo recuerdo',
             'Andrea agregó un recuerdo: Bowling night.', True, 7,
             {'sender_id': self.andrea.id}),
        ]

        for notif_type, title, body, is_read, days_ago, data in NOTIFS:
            n = Notification.objects.create(
                user=self.andrea,
                notification_type=notif_type.upper() if notif_type != 'system' else 'SYSTEM',
                title=title,
                body=body,
                data=data,
                is_read=is_read,
                read_at=self.now - timedelta(days=days_ago) if is_read else None,
            )
            _set_dates(n, created_at=self.now - timedelta(days=days_ago))

        self.stdout.write(self.style.SUCCESS(
            f'  ✓ {len(NOTIFS)} notifications (all 13 types, mix of read/unread)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  18. Device Tokens
    # ═══════════════════════════════════════════════════════════════════

    def _create_device_tokens(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Device Tokens ──'))

        DeviceToken.objects.get_or_create(
            token='seed_fcm_token_andrea_android_001',
            defaults={
                'user': self.andrea,
                'platform': 'android',
                'device_id': 'emulator-5554',
                'is_active': True,
            },
        )
        DeviceToken.objects.get_or_create(
            token='seed_fcm_token_andrea_web_001',
            defaults={
                'user': self.andrea,
                'platform': 'web',
                'is_active': True,
            },
        )

        self.stdout.write(self.style.SUCCESS('  ✓ 2 device tokens (android + web)'))

    # ═══════════════════════════════════════════════════════════════════
    #  19. Billing (Subscription + Payment + Invoice)
    # ═══════════════════════════════════════════════════════════════════

    def _create_billing(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Billing ──'))

        # Payment method
        pm, _ = PaymentMethod.objects.get_or_create(
            user=self.andrea,
            external_id='pm_seed_stripe_001',
            defaults={
                'provider': 'stripe',
                'method_type': 'card',
                'last_four': '4242',
                'card_brand': 'Visa',
                'exp_month': 12,
                'exp_year': 2028,
                'billing_email': self.andrea.email,
                'is_default': True,
                'is_valid': True,
            },
        )

        # Active premium subscription for Andrea
        sub_start = self.now - timedelta(days=20)
        sub, _ = Subscription.objects.get_or_create(
            user=self.andrea,
            plan=self.premium_plan,
            status='active',
            defaults={
                'external_id': 'sub_seed_stripe_001',
                'started_at': sub_start,
                'current_period_start': sub_start,
                'current_period_end': sub_start + timedelta(days=30),
                'default_payment_method': pm,
                'billing_cycle_count': 1,
            },
        )

        # Invoice (paid)
        inv, _ = Invoice.objects.get_or_create(
            invoice_number='INV-2026-00001',
            defaults={
                'user': self.andrea,
                'subscription': sub,
                'status': 'paid',
                'currency': 'USD',
                'subtotal': Decimal('0.99'),
                'tax': Decimal('0.16'),
                'total': Decimal('1.15'),
                'amount_paid': Decimal('1.15'),
                'amount_due': Decimal('0.00'),
                'invoice_date': sub_start,
                'paid_at': sub_start,
                'period_start': sub_start,
                'period_end': sub_start + timedelta(days=30),
                'billing_name': self.andrea.full_name,
                'billing_email': self.andrea.email,
            },
        )

        # Invoice item
        InvoiceItem.objects.get_or_create(
            invoice=inv,
            item_type='subscription',
            defaults={
                'description': 'SquadUp Premium - Mensual',
                'quantity': 1,
                'unit_price': Decimal('0.99'),
                'amount': Decimal('0.99'),
                'plan': self.premium_plan,
                'period_start': sub_start,
                'period_end': sub_start + timedelta(days=30),
            },
        )

        # Payment record
        Payment.objects.get_or_create(
            invoice=inv,
            external_id='pi_seed_stripe_001',
            defaults={
                'payment_method': pm,
                'provider': 'stripe',
                'status': 'succeeded',
                'currency': 'USD',
                'amount': Decimal('1.15'),
                'processed_at': sub_start,
            },
        )

        # Coupon (available but unused)
        coupon, _ = Coupon.objects.get_or_create(
            code='SQUADUP50',
            defaults={
                'discount_type': 'percentage',
                'amount': Decimal('50.00'),
                'duration': 'once',
                'max_redemptions': 100,
                'times_redeemed': 3,
                'valid_until': self.now + timedelta(days=60),
                'is_active': True,
            },
        )
        coupon.applicable_plans.add(self.premium_plan)

        # Free subscriptions for other users
        for user in self.users[1:]:  # Skip Andrea (already premium)
            Subscription.objects.get_or_create(
                user=user,
                plan=self.free_plan,
                defaults={
                    'status': 'active',
                    'started_at': self.now - timedelta(days=30),
                    'current_period_start': self.now - timedelta(days=30),
                    'current_period_end': self.now + timedelta(days=36500),
                },
            )

        self.stdout.write(self.style.SUCCESS(
            '  ✓ 1 payment method + 1 premium subscription + 1 invoice + 1 payment\n'
            '  ✓ 1 coupon (SQUADUP50) + 19 free subscriptions'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  20. Reports
    # ═══════════════════════════════════════════════════════════════════

    def _create_reports(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Reports ──'))

        Report.objects.get_or_create(
            reporter=self.andrea,
            report_type='user',
            target_id=self.valentina.id,
            defaults={
                'reason': 'spam',
                'description': 'Envía mensajes no deseados repetidamente.',
                'status': 'pending',
            },
        )
        Report.objects.get_or_create(
            reporter=self.andrea,
            report_type='message',
            target_id=1,  # Generic message ID
            defaults={
                'reason': 'harassment',
                'description': 'Mensaje ofensivo e irrespetuoso.',
                'status': 'reviewed',
                'reviewed_at': self.now - timedelta(days=5),
            },
        )

        self.stdout.write(self.style.SUCCESS('  ✓ 2 reports (spam + harassment)'))

    # ═══════════════════════════════════════════════════════════════════
    #  21. Match Mutes
    # ═══════════════════════════════════════════════════════════════════

    def _create_match_mutes(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n── Match Mutes ──'))

        # Andrea doesn't want notifications from the active match anymore? No.
        # Actually, let's NOT mute the active match. Instead, skip this if no
        # extra matches exist. For completeness, we can mute from another user's perspective.
        # Let's keep it simple — no mutes for Andrea to test both states.
        self.stdout.write('  (skipped — no muted matches for main user)')

    # ═══════════════════════════════════════════════════════════════════
    #  Summary
    # ═══════════════════════════════════════════════════════════════════

    def _print_summary(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n' + '═' * 60))
        self.stdout.write(self.style.SUCCESS('  SEED COMPLETE'))
        self.stdout.write('═' * 60)
        self.stdout.write(f'''
  Main user:    {self.andrea.full_name} ({self.andrea.email})
  Firebase UID: {self.main_uid}
  Plan:         Premium (active subscription)

  ── Data created ──
  Users:              {User.objects.count()}
  Profiles:           {Profile.objects.count()}
  Profile Photos:     {ProfilePhoto.objects.count()}
  Friendships:        {Friendship.objects.count()}
  Groups:             {Group.objects.count()}
  Group Memberships:  {GroupMembership.objects.count()}
  Group Invitations:  {GroupInvitation.objects.count()}
  Blitz Sessions:     {Blitz.objects.count()}
  Blitz Interactions: {BlitzInteraction.objects.count()}
  Blitz Votes:        {BlitzVote.objects.count()}
  Matches:            {Match.objects.count()}
  Chats:              {Chat.objects.count()}
  Messages:           {Message.objects.count()}
  Match Activities:   {MatchActivity.objects.count()}
  Meetup Plans:       {MeetupPlan.objects.count()}
  Memories:           {Memory.objects.count()}
  Memory Photos:      {MemoryPhoto.objects.count()}
  Solo Matches:       {SoloMatch.objects.count()}
  Solo Coordinations: {SoloCoordination.objects.count()}
  Notifications:      {Notification.objects.count()}
  Device Tokens:      {DeviceToken.objects.count()}
  Plans:              {Plan.objects.count()}
  Plan Features:      {PlanFeature.objects.count()}
  Subscriptions:      {Subscription.objects.count()}
  Payment Methods:    {PaymentMethod.objects.count()}
  Invoices:           {Invoice.objects.count()}
  Payments:           {Payment.objects.count()}
  Coupons:            {Coupon.objects.count()}
  Reports:            {Report.objects.count()}

  ── Scenarios covered for {self.andrea.first_name} ──
  Friendships:  accepted(2), pending-sent(1), pending-received(1), rejected(1), blocked(1)
  Groups:       created+admin(1), member(1), invited-pending(1), invited-declined(1)
  Blitz:        active-democratic(1), matched(1), expired(1), cancelled(1)
  Interactions: mutual-match(2), democratic-pending(1), received-like(1), 3 votes
  Match:        active with chat, activities, meetup plans, memories
  Meetup Plans: proposed(1), accepted(1), confirmed(1), completed(1), cancelled(1)
  Memories:     outing+photos(1), photo+photo(1), note(1)
  Solo Mode:    pending-sent(1), pending-recv(1), matched(1), coordinating(1),
                ready(1), started(1), expired(1), cancelled(1)
  Coordinations: waiting(1), waiting+prefs(1), both_ready(1), started(1)
  Notifications: all 13 types, mix read/unread
  Billing:      premium subscription, stripe card, paid invoice, coupon
  Reports:      spam(1), harassment(1)

  ── Validate manually ──
  1. Login as {self.andrea.email} (uid: {self.main_uid})
  2. Home: recent match card, groups, stats
  3. Matches tab: active match with chat, solo matches section
  4. Blitz tab: active session with 45min, democratic vote pending
  5. Heat Map: run `python manage.py seed_heatmap` for location data
  6. Profile: stats (groups, matches, memories), premium badge
  7. Settings: subscription section shows Premium active
  8. Notifications: all types visible, unread count > 0
  9. Solo Mode: all 8 statuses in connections, coordination rooms
  10. Chat: group chat + solo chats with read/unread messages
''')
