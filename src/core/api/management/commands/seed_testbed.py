"""
Unified testbed seeder: 4 real Firebase Auth users with every feature covered.

Creates Andrea, Carlos, Sofía, and Mateo — all loginable on web and mobile —
fully interlinked with groups, blitz sessions, matches, solo matches, chats,
billing, heat map, notifications, and more.

Usage:
    python manage.py seed_testbed                  # Full seed with real Firebase users
    python manage.py seed_testbed --flush          # Wipe all data first, then seed
    python manage.py seed_testbed --skip-firebase  # Use fake UIDs (for CI/no Firebase credentials)
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
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
    LocationLog,
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
    """Override auto_now_add / auto_now fields via raw UPDATE."""
    if kwargs:
        type(obj).objects.filter(pk=obj.pk).update(**kwargs)


def _avatar(n):
    return f'https://i.pravatar.cc/400?img={n}'


def _jitter(base, spread=0.003):
    """Add small random offset to a coordinate."""
    return float(base) + random.uniform(-spread, spread)


# ── Tijuana heat-map zones (reused from seed_heatmap.py) ──────────────
ZONES = [
    {'id': 'tj_zona_rio', 'name': 'Zona Rio', 'lat': 32.5215, 'lng': -117.0115,
     'activity_level': 'high', 'peak_hour': 20,
     'trend': {'6pm': 3, '7pm': 5, '8pm': 8, '9pm': 6, '10pm': 4},
     'activities': ['food', 'drinks', 'coffee']},
    {'id': 'tj_playas', 'name': 'Playas de Tijuana', 'lat': 32.5290, 'lng': -117.1200,
     'activity_level': 'medium', 'peak_hour': 16,
     'trend': {'2pm': 2, '3pm': 4, '4pm': 5, '5pm': 4, '6pm': 3},
     'activities': ['outdoors', 'sports', 'chill']},
    {'id': 'tj_centro', 'name': 'Centro', 'lat': 32.5300, 'lng': -117.0183,
     'activity_level': 'high', 'peak_hour': 21,
     'trend': {'7pm': 4, '8pm': 6, '9pm': 8, '10pm': 7, '11pm': 5, '12am': 2},
     'activities': ['party', 'drinks', 'music']},
    {'id': 'tj_la_cacho', 'name': 'La Cacho', 'lat': 32.5198, 'lng': -117.0289,
     'activity_level': 'medium', 'peak_hour': 19,
     'trend': {'5pm': 2, '6pm': 3, '7pm': 5, '8pm': 4, '9pm': 3},
     'activities': ['food', 'coffee', 'explore']},
    {'id': 'tj_gastronomica', 'name': 'Zona Gastronomica', 'lat': 32.5156, 'lng': -117.0107,
     'activity_level': 'high', 'peak_hour': 14,
     'trend': {'12pm': 3, '1pm': 5, '2pm': 7, '3pm': 5, '4pm': 3},
     'activities': ['food', 'coffee', 'drinks']},
    {'id': 'tj_otay', 'name': 'Otay', 'lat': 32.5523, 'lng': -116.9711,
     'activity_level': 'low', 'peak_hour': 17,
     'trend': {'4pm': 1, '5pm': 3, '6pm': 2, '7pm': 1},
     'activities': ['explore', 'fitness', 'sports']},
    {'id': 'tj_hipodromo', 'name': 'Hipodromo', 'lat': 32.5102, 'lng': -117.0362,
     'activity_level': 'medium', 'peak_hour': 8,
     'trend': {'6am': 2, '7am': 4, '8am': 5, '9am': 3, '5pm': 3, '6pm': 4},
     'activities': ['fitness', 'outdoors', 'chill']},
    {'id': 'tj_revolucion', 'name': 'Av. Revolucion', 'lat': 32.5300, 'lng': -117.0230,
     'activity_level': 'high', 'peak_hour': 22,
     'trend': {'8pm': 3, '9pm': 5, '10pm': 7, '11pm': 6, '12am': 4},
     'activities': ['party', 'drinks', 'music']},
    {'id': 'tj_chapultepec', 'name': 'Chapultepec', 'lat': 32.5178, 'lng': -117.0205,
     'activity_level': 'medium', 'peak_hour': 15,
     'trend': {'12pm': 2, '1pm': 3, '2pm': 4, '3pm': 4, '4pm': 3},
     'activities': ['study', 'coffee', 'gaming']},
    {'id': 'tj_agua_caliente', 'name': 'Agua Caliente', 'lat': 32.5070, 'lng': -117.0120,
     'activity_level': 'low', 'peak_hour': 18,
     'trend': {'5pm': 2, '6pm': 3, '7pm': 2},
     'activities': ['gaming', 'chill', 'food']},
]

HEATMAP_COUNTS = {
    'last_24h': {'min': 4, 'max': 8},
    'last_7d': {'min': 3, 'max': 6},
    'last_30d': {'min': 2, 'max': 5},
}

# ── The 4 testbed users ──────────────────────────────────────────────
USERS = [
    # (first, last, email, password, avatar_num)
    ('Andrea', 'Salazar', 'andrea@squadup.test', 'SquadUp2026!', 22),
    ('Carlos', 'Mendoza', 'carlos@squadup.test', 'SquadUp2026!', 11),
    ('Sofía', 'Luna', 'sofia@squadup.test', 'SquadUp2026!', 25),
    ('Mateo', 'Rivera', 'mateo@squadup.test', 'SquadUp2026!', 8),
]

PASSWORD = 'SquadUp2026!'

# ── NPC users (fake UIDs, for swiping content) ───────────────────────
NPC_USERS = [
    # (first, last, avatar_num, bio, interests, age, gender)
    ('Mariana', 'López', 32, 'Foodie y viajera. Me encanta conocer gente nueva.',
     ['food', 'travel', 'coffee', 'art', 'chill'], 25, 'Mujer'),
    ('Diego', 'Ramírez', 12, 'Estudiante de diseño. Fan de la fotografía callejera.',
     ['photography', 'art', 'coffee', 'music'], 23, 'Hombre'),
    ('Valentina', 'Cruz', 44, 'Artista digital y DJ los fines de semana.',
     ['art', 'music', 'party', 'drinks'], 23, 'Mujer'),
    ('Javier', 'Torres', 14, 'Desarrollador web. Café es mi gasolina.',
     ['gaming', 'coffee', 'music'], 26, 'Hombre'),
    ('Camila', 'Ortiz', 26, 'Psicóloga. Me encanta la música en vivo.',
     ['music', 'chill', 'art', 'coffee', 'outdoors'], 24, 'Mujer'),
    ('Sebastián', 'Flores', 15, 'Surfista y fotógrafo de naturaleza.',
     ['sports', 'outdoors', 'photography', 'travel'], 27, 'Hombre'),
    ('Isabella', 'Morales', 45, 'Bailarina y maestra de yoga.',
     ['sports', 'chill', 'music', 'art'], 22, 'Mujer'),
    ('Andrés', 'Silva', 16, 'Ingeniero civil. Fan del ciclismo.',
     ['sports', 'outdoors', 'coffee'], 28, 'Hombre'),
    ('Luciana', 'Vargas', 29, 'Diseñadora de modas.',
     ['art', 'party', 'drinks', 'travel'], 24, 'Mujer'),
    ('Emilio', 'Castillo', 17, 'Emprendedor tech. Weekend warrior.',
     ['gaming', 'sports', 'food', 'drinks'], 26, 'Hombre'),
    ('Renata', 'Aguilar', 33, 'Bióloga marina. Amante del océano.',
     ['outdoors', 'travel', 'photography', 'chill'], 25, 'Mujer'),
    ('Santiago', 'Peña', 18, 'Músico y productor. Siempre en busca del ritmo.',
     ['music', 'party', 'drinks', 'art'], 27, 'Hombre'),
    ('Daniela', 'Ríos', 34, 'Periodista. Curiosa por naturaleza.',
     ['travel', 'food', 'coffee', 'art', 'photography'], 23, 'Mujer'),
    ('Nicolás', 'Guzmán', 19, 'Arquitecto. Los detalles importan.',
     ['art', 'coffee', 'outdoors', 'photography'], 29, 'Hombre'),
    ('Fernanda', 'Navarro', 35, 'Veterinaria. 3 gatos, 1 perro.',
     ['chill', 'coffee', 'food', 'outdoors'], 22, 'Mujer'),
    ('Pablo', 'Medina', 20, 'Foodie profesional. Conoce cada taquería de TJ.',
     ['food', 'drinks', 'coffee', 'music', 'chill'], 24, 'Hombre'),
]

# ── NPC Group Blitzes (discoverable by Andrea in leader mode) ────────
NPC_GROUPS = [
    # (group_name, description, admin_idx, member_idxs, activity, image_seed)
    ('Squad Tijuana', 'Los originales de TJ.', 11, [12], 'drinks', 'squadtj'),
    ('Foodies TJ', 'Si no es con hambre, no es plan.', 15, [3], 'food', 'foodies'),
    ('Night Owls', 'La noche es joven.', 7, [8], 'party', 'nightowls'),
    ('Weekend Warriors', 'Para los que viven el fin de semana.', 9, [10], 'sports', 'warriors'),
    ('Café & Chill', 'Un café y buena plática.', 4, [6], 'coffee', 'cafechill'),
    ('Art District', 'Cultura y arte por TJ.', 2, [0], 'art', 'artdistrict'),
    ('Ruta Gastro', 'Probando cada rincón gastronómico.', 15, [12], 'food', 'rutagastro'),
    ('Beach Vibes', 'Sol, arena y buen rollo.', 5, [14], 'outdoors', 'beachvibes'),
    ('Music Crew', 'Buscando el mejor beat.', 11, [8], 'music', 'musiccrew'),
    ('Runners TJ', 'Corriendo por toda la ciudad.', 7, [5], 'sports', 'runnerstj'),
]


class Command(BaseCommand):
    help = 'Seed unified testbed: 4 real Firebase users with every feature covered'

    def add_arguments(self, parser):
        parser.add_argument(
            '--flush', action='store_true',
            help='Delete ALL existing data before seeding',
        )
        parser.add_argument(
            '--skip-firebase', action='store_true',
            help='Use fake UIDs instead of real Firebase Auth users (for CI)',
        )

    def handle(self, *args, **options):
        self.now = timezone.now()
        self.skip_firebase = options['skip_firebase']

        if options['flush']:
            self._flush()

        self._disconnect_signals()

        try:
            with transaction.atomic():
                self._phase_01_foundation()
                self._phase_02_groups()
                self._phase_03_blitz_sessions()
                self._phase_04_interactions_votes()
                self._phase_05_group_match()
                self._phase_06_solo_mode()
                self._phase_07_npc_discoverable()
                self._phase_08_memories()
                self._phase_09_notifications()
                self._phase_10_heatmap()
                self._phase_11_billing()
                self._phase_12_misc()
        finally:
            self._reconnect_signals()

        self._print_summary()

    # ═══════════════════════════════════════════════════════════════════
    #  Signal management
    # ═══════════════════════════════════════════════════════════════════

    def _disconnect_signals(self):
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
        self.stdout.write('  Signals disconnected')

    def _reconnect_signals(self):
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
        self.stdout.write('  Signals reconnected')

    # ═══════════════════════════════════════════════════════════════════
    #  Flush
    # ═══════════════════════════════════════════════════════════════════

    def _flush(self):
        self.stdout.write(self.style.WARNING('\n  Flushing all data...'))
        for model in [
            MemoryPhoto, Memory, MeetupPlan, MatchActivity, MatchMute,
            Message, BlitzVote, BlitzInteraction,
            SoloCoordination, SoloMatch, Match, Chat, Blitz,
            LocationLog, ZoneStats,
            GroupInvitation, GroupMembership, Group,
            Friendship, Report, Notification, DeviceToken,
            ProfilePhoto, Profile,
            Payment, InvoiceItem, Invoice,
            Subscription, PaymentMethod, PlanFeature, Plan, Coupon,
            User,
        ]:
            try:
                n = model.objects.all().delete()[0]
                if n:
                    self.stdout.write(f'    Deleted {n} {model.__name__}')
            except Exception:
                pass
        self.stdout.write(self.style.SUCCESS('  Flush complete\n'))

    # ═══════════════════════════════════════════════════════════════════
    #  Firebase helpers
    # ═══════════════════════════════════════════════════════════════════

    def _ensure_firebase_user(self, email, password, display_name):
        """Create or update a Firebase Auth user. Returns the UID."""
        import os
        import firebase_admin
        from firebase_admin import credentials, auth as firebase_auth

        # Initialize Firebase if needed
        try:
            firebase_admin.get_app()
        except ValueError:
            creds_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
            if os.path.exists(creds_path):
                cred = credentials.Certificate(creds_path)
                firebase_admin.initialize_app(cred)
            else:
                self.stderr.write(self.style.ERROR(
                    f'Firebase credentials not found at {creds_path}\n'
                    f'Use --skip-firebase to seed with fake UIDs.'
                ))
                raise SystemExit(1)

        try:
            existing = firebase_auth.get_user_by_email(email)
            firebase_auth.update_user(existing.uid, password=password)
            return existing.uid
        except firebase_auth.UserNotFoundError:
            fb_user = firebase_auth.create_user(
                email=email,
                password=password,
                display_name=display_name,
                email_verified=True,
            )
            return fb_user.uid

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 1 — Foundation (Plans, Users, Profiles, Photos, Friendships)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_01_foundation(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 1: Foundation =='))

        # ── Plans ──
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
        self.stdout.write(self.style.SUCCESS('  Plans: Free + Premium with 10 features each'))

        # ── 4 Users (Firebase or fake UIDs) ──
        d30 = self.now - timedelta(days=30)
        self.user_data = {}
        for i, (first, last, email, password, avatar_num) in enumerate(USERS):
            display_name = f'{first} {last}'

            if self.skip_firebase:
                uid = f'testbed_{first.lower()}_{i+1:03d}'
            else:
                uid = self._ensure_firebase_user(email, password, display_name)
                self.stdout.write(f'    Firebase: {email} -> {uid}')

            user, created = User.objects.get_or_create(
                firebase_uid=uid,
                defaults={
                    'first_name': first,
                    'last_name': last,
                    'email': email,
                    'profile_photo': _avatar(avatar_num),
                    'is_verified': True,
                    'is_active': True,
                    'role': 'REGULAR',
                },
            )
            if not created:
                # Update in case user already exists with different data
                User.objects.filter(pk=user.pk).update(
                    first_name=first, last_name=last, email=email,
                    profile_photo=_avatar(avatar_num),
                    is_verified=True, is_active=True,
                )
                user.refresh_from_db()
            else:
                _set_dates(user, created_at=d30 + timedelta(hours=i))

            self.user_data[first.lower()] = user

        self.andrea = self.user_data['andrea']
        self.carlos = self.user_data['carlos']
        self.sofia = self.user_data['sofía']
        self.mateo = self.user_data['mateo']
        self.stdout.write(self.style.SUCCESS(f'  Users: 4 created (firebase={not self.skip_firebase})'))

        # ── 4 Profiles ──
        tj_loc = {'lat': 32.5149, 'lng': -117.0382, 'city': 'Tijuana, BC'}
        PROFILES = [
            (self.andrea, 'Aventurera y amante del café. Siempre buscando nuevas experiencias.',
             ['coffee', 'outdoors', 'music', 'travel', 'photography'], 24, 'Mujer'),
            (self.carlos, 'Gamer de corazón y deportista de fin de semana.',
             ['gaming', 'sports', 'drinks', 'party', 'music'], 22, 'Hombre'),
            (self.sofia, 'Corredora y amante de los perros. Solo mode activo.',
             ['sports', 'outdoors', 'chill', 'food'], 21, 'Mujer'),
            (self.mateo, 'Chef en formación. Siempre probando recetas nuevas.',
             ['food', 'coffee', 'travel', 'chill'], 25, 'Hombre'),
        ]
        for user, bio, interests, age, gender in PROFILES:
            Profile.objects.update_or_create(
                user=user,
                defaults={
                    'bio': bio, 'interests': interests,
                    'age': age, 'gender': gender,
                    'default_location': tj_loc,
                },
            )
        self.stdout.write(self.style.SUCCESS('  Profiles: 4'))

        # ── 11 ProfilePhotos ──
        photo_count = 0
        # Andrea: 4 gallery photos
        for i in range(4):
            _, created = ProfilePhoto.objects.get_or_create(
                user=self.andrea, order=i,
                defaults={
                    'image_url': f'https://picsum.photos/seed/andrea{i}/400/400',
                    'caption': ['En la playa', 'Con amigos', 'Café favorito', 'Explorando'][i],
                },
            )
            if created:
                photo_count += 1
        # Carlos: 2
        for i in range(2):
            _, created = ProfilePhoto.objects.get_or_create(
                user=self.carlos, order=i,
                defaults={
                    'image_url': f'https://picsum.photos/seed/carlos{i}/400/400',
                },
            )
            if created:
                photo_count += 1
        # Sofía: 2
        for i in range(2):
            _, created = ProfilePhoto.objects.get_or_create(
                user=self.sofia, order=i,
                defaults={
                    'image_url': f'https://picsum.photos/seed/sofia{i}/400/400',
                },
            )
            if created:
                photo_count += 1
        # Mateo: 3
        for i in range(3):
            _, created = ProfilePhoto.objects.get_or_create(
                user=self.mateo, order=i,
                defaults={
                    'image_url': f'https://picsum.photos/seed/mateo{i}/400/400',
                },
            )
            if created:
                photo_count += 1
        self.stdout.write(self.style.SUCCESS(f'  ProfilePhotos: {photo_count}'))

        # ── 6 Friendships (all C(4,2) pairs, all accepted) ──
        FRIENDSHIPS = [
            # (from, to, source)
            (self.andrea, self.carlos, 'direct'),
            (self.andrea, self.sofia, 'direct'),
            (self.andrea, self.mateo, 'solo'),
            (self.carlos, self.sofia, 'solo'),
            (self.carlos, self.mateo, 'direct'),
            (self.sofia, self.mateo, 'solo'),
        ]
        friend_count = 0
        for user_from, user_to, source in FRIENDSHIPS:
            f, created = Friendship.objects.get_or_create(
                user_from=user_from, user_to=user_to,
                defaults={'status': 'accepted', 'source': source},
            )
            if created:
                ts = self.now - timedelta(days=random.randint(10, 25))
                _set_dates(f, created_at=ts, updated_at=ts)
                friend_count += 1
        self.stdout.write(self.style.SUCCESS(f'  Friendships: {friend_count} (all accepted)'))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 2 — Groups (5 total)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_02_groups(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 2: Groups =='))

        d20 = self.now - timedelta(days=20)

        # 1. Los Aventureros: Andrea (admin) + Carlos
        self.grp_aventureros, _ = Group.objects.get_or_create(
            name='Los Aventureros',
            defaults={
                'description': 'Explorando Tijuana un fin de semana a la vez.',
                'creator': self.andrea,
                'image_url': 'https://picsum.photos/seed/aventureros/200/200',
            },
        )
        _set_dates(self.grp_aventureros, created_at=d20)
        for user, role in [(self.andrea, 'admin'), (self.carlos, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_aventureros, defaults={'role': role},
            )

        # 2. Vibra Nocturna: Andrea (admin) + Carlos + Sofía
        self.grp_vibra, _ = Group.objects.get_or_create(
            name='Vibra Nocturna',
            defaults={
                'description': 'La noche apenas empieza.',
                'creator': self.andrea,
                'image_url': 'https://picsum.photos/seed/vibra/200/200',
            },
        )
        _set_dates(self.grp_vibra, created_at=d20 + timedelta(days=1))
        for user, role in [(self.andrea, 'admin'), (self.carlos, 'member'), (self.sofia, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_vibra, defaults={'role': role},
            )

        # 3. Duo Andrea-Mateo (solo duo)
        self.grp_duo_am, _ = Group.objects.get_or_create(
            name='Andrea & Mateo',
            defaults={
                'description': 'Solo Mode duo',
                'creator': self.andrea,
                'metadata': {'source': 'solo'},
            },
        )
        for user, role in [(self.andrea, 'admin'), (self.mateo, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_duo_am, defaults={'role': role},
            )

        # 4. Duo Sofía-Carlos (solo duo)
        self.grp_duo_sc, _ = Group.objects.get_or_create(
            name='Sofía & Carlos',
            defaults={
                'description': 'Solo Mode duo',
                'creator': self.sofia,
                'metadata': {'source': 'solo'},
            },
        )
        for user, role in [(self.sofia, 'admin'), (self.carlos, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_duo_sc, defaults={'role': role},
            )

        # 5. Duo Sofía-Mateo (created by started solo match)
        self.grp_duo_sm, _ = Group.objects.get_or_create(
            name='Sofía & Mateo',
            defaults={
                'description': 'Solo Mode duo (started)',
                'creator': self.sofia,
                'metadata': {'source': 'solo'},
            },
        )
        for user, role in [(self.sofia, 'admin'), (self.mateo, 'member')]:
            GroupMembership.objects.get_or_create(
                user=user, group=self.grp_duo_sm, defaults={'role': role},
            )

        self.stdout.write(self.style.SUCCESS(
            '  Groups: 5 (2 regular + 3 solo duos) with memberships'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 3 — Blitz Sessions (6)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_03_blitz_sessions(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 3: Blitz Sessions =='))

        tj_loc = {'lat': 32.5149, 'lng': -117.0382, 'address': 'Tijuana, BC', 'radius_km': 5}

        # 1. Active Leader: Los Aventureros, expires now+45min
        self.blitz_active_leader, _ = Blitz.objects.get_or_create(
            group=self.grp_aventureros,
            leader=self.andrea,
            status='active',
            swipe_mode='leader',
            defaults={
                'location': tj_loc,
                'activity_type': 'coffee',
                'min_opponent_size': 2,
                'max_opponent_size': 5,
                'expires_at': self.now + timedelta(minutes=45),
                'metadata': {'activities': ['coffee', 'food', 'chill']},
            },
        )

        # 2. Active Democratic: Vibra Nocturna, expires now+30min
        self.blitz_active_demo, _ = Blitz.objects.get_or_create(
            group=self.grp_vibra,
            leader=self.andrea,
            status='active',
            swipe_mode='democratic',
            defaults={
                'location': tj_loc,
                'activity_type': 'drinks',
                'min_opponent_size': 2,
                'expires_at': self.now + timedelta(minutes=30),
                'metadata': {'activities': ['drinks', 'party', 'music']},
            },
        )

        # 3. Matched A: Los Aventureros, 14 days ago
        self.blitz_matched_a, _ = Blitz.objects.get_or_create(
            group=self.grp_aventureros,
            leader=self.andrea,
            status='matched',
            activity_type='outdoors',
            defaults={
                'location': tj_loc,
                'swipe_mode': 'leader',
                'min_opponent_size': 2,
                'expires_at': self.now - timedelta(days=14, hours=-1),
            },
        )
        _set_dates(self.blitz_matched_a,
                   started_at=self.now - timedelta(days=14),
                   created_at=self.now - timedelta(days=14))

        # 4. Matched B: Vibra Nocturna, 14 days ago
        self.blitz_matched_b, _ = Blitz.objects.get_or_create(
            group=self.grp_vibra,
            leader=self.andrea,
            status='matched',
            activity_type='music',
            defaults={
                'location': tj_loc,
                'swipe_mode': 'democratic',
                'min_opponent_size': 2,
                'expires_at': self.now - timedelta(days=14, hours=-1),
            },
        )
        _set_dates(self.blitz_matched_b,
                   started_at=self.now - timedelta(days=14),
                   created_at=self.now - timedelta(days=14))

        # 5. Expired: Los Aventureros, 2 days ago
        self.blitz_expired, _ = Blitz.objects.get_or_create(
            group=self.grp_aventureros,
            leader=self.carlos,
            status='expired',
            activity_type='sports',
            defaults={
                'location': tj_loc,
                'min_opponent_size': 2,
                'expires_at': self.now - timedelta(days=2),
            },
        )
        _set_dates(self.blitz_expired,
                   started_at=self.now - timedelta(days=2, hours=1),
                   created_at=self.now - timedelta(days=2, hours=1))

        # 6. Cancelled: Vibra Nocturna, 3 days ago
        self.blitz_cancelled, _ = Blitz.objects.get_or_create(
            group=self.grp_vibra,
            leader=self.carlos,
            status='cancelled',
            activity_type='party',
            defaults={
                'location': tj_loc,
                'min_opponent_size': 2,
                'expires_at': self.now - timedelta(days=3),
            },
        )
        _set_dates(self.blitz_cancelled,
                   started_at=self.now - timedelta(days=3, hours=1),
                   created_at=self.now - timedelta(days=3, hours=1))

        self.stdout.write(self.style.SUCCESS(
            '  Blitzes: 6 (2 active, 2 matched, 1 expired, 1 cancelled)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 4 — Interactions & Votes
    # ═══════════════════════════════════════════════════════════════════

    def _phase_04_interactions_votes(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 4: Interactions & Votes =='))

        # Mutual likes: Matched A <-> Matched B (these created the match)
        int1, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_matched_a, to_blitz=self.blitz_matched_b,
            defaults={'interaction_type': 'like'},
        )
        _set_dates(int1, created_at=self.now - timedelta(days=14))

        int2, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_matched_b, to_blitz=self.blitz_matched_a,
            defaults={'interaction_type': 'like'},
        )
        _set_dates(int2, created_at=self.now - timedelta(days=14))

        # Democratic vote: Active Democratic -> Active Leader, requires_consensus
        int3, created = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_active_demo, to_blitz=self.blitz_active_leader,
            defaults={'interaction_type': 'like', 'requires_consensus': True},
        )
        if created:
            BlitzVote.objects.get_or_create(
                interaction=int3, user=self.andrea,
                defaults={'vote': 'approved', 'voted_at': self.now},
            )
            BlitzVote.objects.get_or_create(
                interaction=int3, user=self.carlos,
                defaults={'vote': 'approved', 'voted_at': self.now - timedelta(minutes=5)},
            )
            BlitzVote.objects.get_or_create(
                interaction=int3, user=self.sofia,
                defaults={'vote': 'pending'},
            )

        # One-way like: Active Leader -> Active Democratic (no reciprocation)
        int4, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_active_leader, to_blitz=self.blitz_active_demo,
            defaults={'interaction_type': 'like'},
        )

        # Skip: Active Leader -> Expired blitz
        int5, _ = BlitzInteraction.objects.get_or_create(
            from_blitz=self.blitz_active_leader, to_blitz=self.blitz_expired,
            defaults={'interaction_type': 'skip'},
        )

        self.stdout.write(self.style.SUCCESS(
            '  Interactions: 5 (2 mutual, 1 democratic+3 votes, 1 one-way, 1 skip)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 5 — Group Match + Chat + Activities + MeetupPlan
    # ═══════════════════════════════════════════════════════════════════

    def _phase_05_group_match(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 5: Group Match =='))

        # Chat for the match
        self.chat_match = Chat.objects.create(
            is_active=True,
            last_message_at=self.now - timedelta(hours=2),
            last_message_preview='Perfecto, nos vemos mañana.',
        )
        self.chat_match.participants.add(
            self.andrea, self.carlos, self.sofia,
        )
        _set_dates(self.chat_match, created_at=self.now - timedelta(days=14))

        # Match (blitz_1.id < blitz_2.id convention)
        b1, b2 = sorted(
            [self.blitz_matched_a, self.blitz_matched_b], key=lambda b: b.id,
        )
        self.match_active, _ = Match.objects.get_or_create(
            blitz_1=b1, blitz_2=b2,
            defaults={
                'status': 'active',
                'matched_at': self.now - timedelta(days=14),
                'chat': self.chat_match,
            },
        )
        _set_dates(self.match_active, created_at=self.now - timedelta(days=14))

        # 8 Messages spanning 14 days
        msgs = [
            (None, 'system', '¡Match creado! Los Aventureros y Vibra Nocturna.', -14 * 24),
            (self.andrea, 'text', '¡Hola a todos! ¿Qué planes tienen?', -14 * 24 + 1),
            (self.carlos, 'text', 'Hey! Buscamos algo chill este fin de semana.', -14 * 24 + 2),
            (self.sofia, 'text', '¡Hola! 👋 Yo quiero explorar Zona Río.', -14 * 24 + 3),
            (self.andrea, 'text', 'Perfecto, ¿saben de algún lugar nuevo?', -13 * 24),
            (self.carlos, 'text', 'Hay un nuevo spot de tacos en Gastronómica.', -10 * 24),
            (self.sofia, 'text', '¡Me apunto! ¿Cuándo vamos?', -5 * 24),
            (self.andrea, 'text', 'Perfecto, nos vemos mañana.', -2),
        ]
        for sender, msg_type, text, hours_ago in msgs:
            m = Message.objects.create(
                chat=self.chat_match,
                sender=sender, text=text,
                message_type=msg_type, is_read=True,
                read_at=self.now - timedelta(hours=max(0, abs(hours_ago) - 1)),
            )
            _set_dates(m, created_at=self.now + timedelta(hours=hours_ago))

        # 3 MatchActivities
        for act_type, triggered_by, desc, days_ago in [
            ('match_created', self.andrea, 'Match creado', -14),
            ('chat_started', self.andrea, 'Chat iniciado', -14),
            ('plan_suggested', self.carlos, 'Carlos propuso tacos en Zona Gastronómica', -10),
        ]:
            ma = MatchActivity.objects.create(
                match=self.match_active,
                activity_type=act_type,
                triggered_by=triggered_by,
                description=desc,
            )
            _set_dates(ma, created_at=self.now + timedelta(days=days_ago))

        # 1 MeetupPlan
        mp = MeetupPlan.objects.create(
            match=self.match_active,
            proposed_by=self.carlos,
            title='Tacos en Zona Gastronómica',
            scheduled_at=self.now + timedelta(days=1),
            location_name='Zona Gastronómica TJ',
            location_address='Blvd. Agua Caliente esq. Tapachula',
            location_coords={'lat': 32.5156, 'lng': -117.0107},
            status='proposed',
        )
        _set_dates(mp, created_at=self.now - timedelta(days=2))

        self.stdout.write(self.style.SUCCESS(
            '  Match: 1 active + chat(8 msgs) + 3 activities + 1 meetup plan'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 6 — Solo Mode (6 matches covering all statuses)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_06_solo_mode(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 6: Solo Mode =='))

        tj_loc = {'lat': 32.5149, 'lng': -117.0382, 'address': 'Tijuana, BC', 'radius_km': 5}

        # ── 1. MATCHED: Andrea <-> Mateo (both prefs set, about to start) ──
        chat_am = Chat.objects.create(
            is_active=True, metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=3),
            last_message_preview='¡Lista para la aventura!',
        )
        chat_am.participants.add(self.andrea, self.mateo)
        _set_dates(chat_am, created_at=self.now - timedelta(days=7))

        sm_matched, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.mateo,
            defaults={
                'status': 'matched',
                'matched_at': self.now - timedelta(days=7),
                'expires_at': self.now + timedelta(days=3),
                'chat': chat_am,
                'group': self.grp_duo_am,
            },
        )
        _set_dates(sm_matched, created_at=self.now - timedelta(days=7))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_matched,
            defaults={
                'status': 'both_ready',
                'user_a_categories': ['coffee', 'food', 'outdoors'],
                'user_a_time': {'date': '2026-02-25', 'start_time': '10:00', 'end_time': '13:00'},
                'user_a_zone': {'name': 'Playas de Tijuana'},
                'user_a_ready': True,
                'user_b_categories': ['coffee', 'chill', 'food'],
                'user_b_time': {'date': '2026-02-25', 'start_time': '10:00', 'end_time': '14:00'},
                'user_b_zone': {'name': 'Playas de Tijuana'},
                'user_b_ready': True,
                'expires_at': self.now + timedelta(days=3),
            },
        )

        # Solo chat messages for Andrea-Mateo
        for sender, text, hours_ago in [
            (None, '¡Conexión mutua! 🎉', 7 * 24),
            (self.andrea, '¡Hola Mateo! 👋', 7 * 24 - 1),
            (self.mateo, 'Hey Andrea! Me da gusto conectar.', 6 * 24),
            (self.andrea, '¡Lista para la aventura!', 3),
        ]:
            m = Message.objects.create(
                chat=chat_am, sender=sender, text=text,
                message_type='system' if sender is None else 'text',
                is_read=True,
            )
            _set_dates(m, created_at=self.now - timedelta(hours=hours_ago))

        # ── 2. COORDINATING: Sofía <-> Carlos (Sofía set prefs, Carlos hasn't) ──
        chat_sc = Chat.objects.create(
            is_active=True, metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=12),
            last_message_preview='¡Coordinemos!',
        )
        chat_sc.participants.add(self.sofia, self.carlos)
        _set_dates(chat_sc, created_at=self.now - timedelta(days=5))

        sm_coordinating, _ = SoloMatch.objects.get_or_create(
            user_a=self.sofia, user_b=self.carlos,
            defaults={
                'status': 'coordinating',
                'matched_at': self.now - timedelta(days=5),
                'expires_at': self.now + timedelta(days=2),
                'chat': chat_sc,
                'group': self.grp_duo_sc,
            },
        )
        _set_dates(sm_coordinating, created_at=self.now - timedelta(days=5))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_coordinating,
            defaults={
                'status': 'waiting',
                'user_a_categories': ['sports', 'outdoors', 'chill'],
                'user_a_time': {'date': '2026-02-26', 'start_time': '16:00', 'end_time': '19:00'},
                'user_a_zone': {'name': 'Playas de Tijuana'},
                'expires_at': self.now + timedelta(days=2),
            },
        )

        for sender, text, hours_ago in [
            (None, '¡Conexión mutua! 🎉', 5 * 24),
            (self.sofia, '¡Coordinemos!', 12),
        ]:
            m = Message.objects.create(
                chat=chat_sc, sender=sender, text=text,
                message_type='system' if sender is None else 'text',
                is_read=True,
            )
            _set_dates(m, created_at=self.now - timedelta(hours=hours_ago))

        # ── 3. PENDING: Andrea -> Carlos (Andrea swiped, Carlos hasn't) ──
        sm_pending, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.carlos,
            defaults={
                'status': 'pending',
                'expires_at': self.now + timedelta(hours=20),
            },
        )
        _set_dates(sm_pending, created_at=self.now - timedelta(hours=4))

        # ── 4. STARTED: Sofía <-> Mateo (blitz created from coordination) ──
        blitz_solo_started, _ = Blitz.objects.get_or_create(
            group=self.grp_duo_sm,
            leader=self.sofia,
            status='active',
            activity_type='outdoors',
            defaults={
                'location': tj_loc,
                'expires_at': self.now + timedelta(minutes=25),
                'metadata': {'activities': ['outdoors', 'chill', 'food']},
            },
        )

        chat_sm = Chat.objects.create(
            is_active=True, metadata={'solo_mode': True},
            last_message_at=self.now - timedelta(hours=1),
            last_message_preview='¡Vamos!',
        )
        chat_sm.participants.add(self.sofia, self.mateo)
        _set_dates(chat_sm, created_at=self.now - timedelta(days=3))

        sm_started, _ = SoloMatch.objects.get_or_create(
            user_a=self.sofia, user_b=self.mateo,
            defaults={
                'status': 'started',
                'matched_at': self.now - timedelta(days=3),
                'chat': chat_sm,
                'group': self.grp_duo_sm,
                'blitz': blitz_solo_started,
                'group_confirmed_a': True,
                'group_confirmed_b': True,
            },
        )
        _set_dates(sm_started, created_at=self.now - timedelta(days=3))
        SoloCoordination.objects.get_or_create(
            solo_match=sm_started,
            defaults={
                'status': 'started',
                'user_a_categories': ['outdoors', 'chill'],
                'user_a_ready': True,
                'user_b_categories': ['food', 'chill'],
                'user_b_ready': True,
            },
        )

        for sender, text, hours_ago in [
            (None, '¡Blitz iniciado! 🚀', 3 * 24),
            (self.mateo, '¡Listo para la aventura!', 3 * 24 - 1),
            (self.sofia, '¡Vamos!', 1),
        ]:
            m = Message.objects.create(
                chat=chat_sm, sender=sender, text=text,
                message_type='system' if sender is None else 'text',
                is_read=True,
            )
            _set_dates(m, created_at=self.now - timedelta(hours=hours_ago))

        # ── 5. EXPIRED: Andrea <-> Sofía (timed out 8 days ago) ──
        sm_expired, _ = SoloMatch.objects.get_or_create(
            user_a=self.andrea, user_b=self.sofia,
            defaults={
                'status': 'expired',
                'matched_at': self.now - timedelta(days=15),
                'expires_at': self.now - timedelta(days=8),
            },
        )
        _set_dates(sm_expired, created_at=self.now - timedelta(days=15))

        # ── 6. CANCELLED: Carlos <-> Mateo (cancelled 12 days ago) ──
        sm_cancelled, _ = SoloMatch.objects.get_or_create(
            user_a=self.carlos, user_b=self.mateo,
            defaults={
                'status': 'cancelled',
                'matched_at': self.now - timedelta(days=18),
                'expires_at': self.now - timedelta(days=12),
            },
        )
        _set_dates(sm_cancelled, created_at=self.now - timedelta(days=18))

        self.stdout.write(self.style.SUCCESS(
            '  Solo Matches: 6 (matched, coordinating, pending, started, expired, cancelled)\n'
            '  Solo Coordinations: 3 (both_ready, waiting, started)\n'
            '  Solo Chats: 3 with messages'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 7 — NPC users, groups, discoverable blitzes, historical
    #            matches, and solo-mode discoverable profiles
    # ═══════════════════════════════════════════════════════════════════

    def _phase_07_npc_discoverable(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 7: NPC Discoverable Content =='))

        tj_loc = {'lat': 32.5149, 'lng': -117.0382, 'address': 'Tijuana, BC', 'radius_km': 5}
        d30 = self.now - timedelta(days=30)

        # ── Create 16 NPC users with profiles ──
        self.npcs = []
        for i, (first, last, avatar, bio, interests, age, gender) in enumerate(NPC_USERS):
            uid = f'npc_{first.lower()}_{i+1:03d}'
            email = f'{first.lower()}.{last.lower()}@npc.squadup.test'
            user, created = User.objects.get_or_create(
                firebase_uid=uid,
                defaults={
                    'first_name': first, 'last_name': last,
                    'email': email,
                    'profile_photo': _avatar(avatar),
                    'is_verified': True, 'is_active': True,
                    'role': 'REGULAR',
                },
            )
            if created:
                _set_dates(user, created_at=d30 + timedelta(hours=i))
            self.npcs.append(user)

            Profile.objects.update_or_create(
                user=user,
                defaults={
                    'bio': bio, 'interests': interests,
                    'age': age, 'gender': gender,
                    'default_location': {'lat': 32.5149, 'lng': -117.0382, 'city': 'Tijuana, BC'},
                },
            )
            # 1–2 gallery photos per NPC
            for j in range(random.randint(1, 2)):
                ProfilePhoto.objects.get_or_create(
                    user=user, order=j,
                    defaults={
                        'image_url': f'https://picsum.photos/seed/{first.lower()}{j}/400/400',
                    },
                )

        self.stdout.write(self.style.SUCCESS(f'  NPC Users: {len(self.npcs)} with profiles & photos'))

        # ── Create 10 NPC groups with active blitzes (discoverable by Andrea) ──
        self.npc_groups = []
        self.npc_active_blitzes = []
        activities_pool = ['coffee', 'food', 'drinks', 'sports', 'music',
                           'party', 'art', 'outdoors', 'chill', 'gaming']

        for grp_name, desc, admin_idx, member_idxs, activity, img_seed in NPC_GROUPS:
            grp, _ = Group.objects.get_or_create(
                name=grp_name,
                defaults={
                    'description': desc,
                    'creator': self.npcs[admin_idx],
                    'image_url': f'https://picsum.photos/seed/{img_seed}/200/200',
                },
            )
            GroupMembership.objects.get_or_create(
                user=self.npcs[admin_idx], group=grp,
                defaults={'role': 'admin'},
            )
            for midx in member_idxs:
                GroupMembership.objects.get_or_create(
                    user=self.npcs[midx], group=grp,
                    defaults={'role': 'member'},
                )
            self.npc_groups.append(grp)

            # Active blitz for this group (Andrea can discover & swipe)
            minutes_left = random.randint(15, 55)
            blitz, _ = Blitz.objects.get_or_create(
                group=grp, leader=self.npcs[admin_idx],
                status='active', activity_type=activity,
                defaults={
                    'location': tj_loc,
                    'swipe_mode': 'leader',
                    'min_opponent_size': 2,
                    'expires_at': self.now + timedelta(minutes=minutes_left),
                    'metadata': {'activities': random.sample(activities_pool, 3)},
                },
            )
            self.npc_active_blitzes.append(blitz)

        self.stdout.write(self.style.SUCCESS(
            f'  NPC Groups: {len(self.npc_groups)} with active blitzes (discoverable)'
        ))

        # ── Historical matched blitzes + matches (past area activity) ──
        historical_count = 0
        for i in range(0, len(self.npc_groups) - 1, 2):
            grp_a = self.npc_groups[i]
            grp_b = self.npc_groups[i + 1]
            admin_a = self.npcs[NPC_GROUPS[i][2]]
            admin_b = self.npcs[NPC_GROUPS[i + 1][2]]
            days_ago = random.randint(3, 20)

            b_a, _ = Blitz.objects.get_or_create(
                group=grp_a, leader=admin_a,
                status='matched', activity_type=NPC_GROUPS[i][4],
                defaults={
                    'location': tj_loc,
                    'swipe_mode': 'leader',
                    'min_opponent_size': 2,
                    'expires_at': self.now - timedelta(days=days_ago, hours=-1),
                },
            )
            _set_dates(b_a,
                       started_at=self.now - timedelta(days=days_ago),
                       created_at=self.now - timedelta(days=days_ago))

            b_b, _ = Blitz.objects.get_or_create(
                group=grp_b, leader=admin_b,
                status='matched', activity_type=NPC_GROUPS[i + 1][4],
                defaults={
                    'location': tj_loc,
                    'swipe_mode': 'leader',
                    'min_opponent_size': 2,
                    'expires_at': self.now - timedelta(days=days_ago, hours=-1),
                },
            )
            _set_dates(b_b,
                       started_at=self.now - timedelta(days=days_ago),
                       created_at=self.now - timedelta(days=days_ago))

            # Mutual likes
            int_ab, _ = BlitzInteraction.objects.get_or_create(
                from_blitz=b_a, to_blitz=b_b,
                defaults={'interaction_type': 'like'},
            )
            _set_dates(int_ab, created_at=self.now - timedelta(days=days_ago))
            int_ba, _ = BlitzInteraction.objects.get_or_create(
                from_blitz=b_b, to_blitz=b_a,
                defaults={'interaction_type': 'like'},
            )
            _set_dates(int_ba, created_at=self.now - timedelta(days=days_ago))

            # Match
            b1, b2 = sorted([b_a, b_b], key=lambda b: b.id)
            chat = Chat.objects.create(
                is_active=True,
                last_message_at=self.now - timedelta(days=days_ago - 1),
                last_message_preview='¡Nos vemos pronto!',
            )
            chat.participants.add(admin_a, admin_b)
            _set_dates(chat, created_at=self.now - timedelta(days=days_ago))

            Match.objects.get_or_create(
                blitz_1=b1, blitz_2=b2,
                defaults={
                    'status': 'active',
                    'matched_at': self.now - timedelta(days=days_ago),
                    'chat': chat,
                },
            )
            historical_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'  Historical Matches: {historical_count} (NPC group pairs)'
        ))

        # ── Some NPC blitzes that already interacted with Andrea's blitzes ──
        # 2 groups already liked Andrea's active leader blitz (received likes)
        for blitz in self.npc_active_blitzes[:2]:
            BlitzInteraction.objects.get_or_create(
                from_blitz=blitz, to_blitz=self.blitz_active_leader,
                defaults={'interaction_type': 'like'},
            )

        # 1 group already liked Andrea's active democratic blitz
        BlitzInteraction.objects.get_or_create(
            from_blitz=self.npc_active_blitzes[2], to_blitz=self.blitz_active_demo,
            defaults={'interaction_type': 'like'},
        )

        self.stdout.write(self.style.SUCCESS(
            '  Received Likes: 3 (NPC groups liked Andrea\'s active blitzes)'
        ))

        # ── Free subscriptions for all NPCs ──
        for npc in self.npcs:
            Subscription.objects.get_or_create(
                user=npc, plan=self.free_plan,
                defaults={
                    'status': 'active',
                    'started_at': self.now - timedelta(days=30),
                    'current_period_start': self.now - timedelta(days=30),
                    'current_period_end': self.now + timedelta(days=36500),
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f'  NPC Subscriptions: {len(self.npcs)} (all Free)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 8 — Memories
    # ═══════════════════════════════════════════════════════════════════

    def _phase_08_memories(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 8: Memories =='))

        # Memory 1: Outing with photos
        mem1 = Memory.objects.create(
            match=self.match_active,
            created_by=self.andrea,
            memory_type='outing',
            title='Tacos con el squad',
            event_date=(self.now - timedelta(days=8)).date(),
            notes='Increíble noche de tacos. Carlos conoce los mejores lugares.',
            location_name='Zona Gastronómica',
        )
        _set_dates(mem1, created_at=self.now - timedelta(days=7))
        MemoryPhoto.objects.create(
            memory=mem1, uploaded_by=self.andrea, order=0,
            image_url='https://picsum.photos/seed/tacos1/600/400',
            caption='Los mejores tacos',
        )
        MemoryPhoto.objects.create(
            memory=mem1, uploaded_by=self.carlos, order=1,
            image_url='https://picsum.photos/seed/tacos2/600/400',
            caption='El equipo',
        )

        # Memory 2: Photo type
        mem2 = Memory.objects.create(
            match=self.match_active,
            created_by=self.sofia,
            memory_type='photo',
            title='Selfie en Zona Río',
            event_date=(self.now - timedelta(days=5)).date(),
            notes='',
        )
        _set_dates(mem2, created_at=self.now - timedelta(days=5))
        MemoryPhoto.objects.create(
            memory=mem2, uploaded_by=self.sofia, order=0,
            image_url='https://picsum.photos/seed/selfie1/600/400',
            caption='Todos juntos',
        )

        self.stdout.write(self.style.SUCCESS(
            '  Memories: 2 (outing + photo) with 3 photos'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 9 — Notifications (15 total, all 13 types)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_09_notifications(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 9: Notifications =='))

        # Notifications for Andrea (8)
        andrea_notifs = [
            ('system', '¡Bienvenida a SquadUp!',
             'Tu cuenta está lista. Completa tu perfil.', True, 30, {}),
            ('blitz_match', '¡Es un Match! 🎉',
             'Los Aventureros y Vibra Nocturna hicieron match.', True, 14,
             {'match_id': self.match_active.id}),
            ('friend_request', 'Nueva solicitud',
             'Carlos Mendoza quiere ser tu amigo.', True, 20,
             {'sender_id': self.carlos.id}),
            ('solo_match', '¡Es un Match!',
             'Tú y Mateo quieren conectar.', True, 7,
             {'sender_id': self.mateo.id}),
            ('blitz_expiring', 'Tu Blitz está por expirar',
             'Los Aventureros tiene 15 minutos restantes.', False, 0,
             {'blitz_id': self.blitz_active_leader.id}),
            ('new_message', 'Nuevo mensaje',
             'Mateo: Hey Andrea! Me da gusto conectar.', False, 0,
             {'sender_id': self.mateo.id}),
            ('meetup_proposed', 'Nuevo plan propuesto',
             'Carlos propuso: Tacos en Zona Gastronómica.', False, 2,
             {'sender_id': self.carlos.id}),
            ('memory_added', 'Nuevo recuerdo',
             'Sofía agregó un recuerdo: Selfie en Zona Río.', True, 5,
             {'sender_id': self.sofia.id}),
        ]

        # Notifications for Carlos (3)
        carlos_notifs = [
            ('system', '¡Bienvenido a SquadUp!',
             'Tu cuenta está lista.', True, 28, {}),
            ('solo_connection', 'Nueva conexión',
             'Andrea quiere conectar contigo.', False, 0,
             {'sender_id': self.andrea.id}),
            ('blitz_vote_request', 'Voto necesario',
             'Andrea propuso dar like. ¡Vota!', False, 0, {}),
        ]

        # Notifications for Sofía (2)
        sofia_notifs = [
            ('group_invite', 'Invitación a grupo',
             'Andrea te invitó a Vibra Nocturna.', True, 18,
             {'sender_id': self.andrea.id}),
            ('blitz_like', 'Un grupo te dio like',
             'Los Aventureros está interesado.', False, 0, {}),
        ]

        # Notifications for Mateo (2)
        mateo_notifs = [
            ('meetup_confirmed', 'Plan confirmado',
             'Tacos en Zona Gastronómica está confirmado.', True, 1, {}),
            ('solo_connection', 'Nueva conexión',
             'Sofía quiere conectar contigo.', False, 3,
             {'sender_id': self.sofia.id}),
        ]

        total = 0
        for user, notifs in [
            (self.andrea, andrea_notifs),
            (self.carlos, carlos_notifs),
            (self.sofia, sofia_notifs),
            (self.mateo, mateo_notifs),
        ]:
            for notif_type, title, body, is_read, days_ago, data in notifs:
                n = Notification.objects.create(
                    user=user,
                    notification_type=notif_type,
                    title=title,
                    body=body,
                    data=data,
                    is_read=is_read,
                    read_at=self.now - timedelta(days=days_ago) if is_read else None,
                )
                _set_dates(n, created_at=self.now - timedelta(days=days_ago))
                total += 1

        self.stdout.write(self.style.SUCCESS(
            f'  Notifications: {total} across 4 users (all 13 types covered)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 10 — Heat Map (Tijuana)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_10_heatmap(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 10: Heat Map =='))

        now = self.now
        users = [self.andrea, self.carlos, self.sofia, self.mateo]

        # Need at least one group and blitz per activity for LocationLogs
        all_activities = sorted({act for z in ZONES for act in z['activities']})
        activity_blitzes = {}
        for activity in all_activities:
            blitz, _ = Blitz.objects.get_or_create(
                group=self.grp_aventureros,
                leader=self.andrea,
                activity_type=activity,
                status='expired',
                defaults={
                    'location': {
                        'lat': 32.5149, 'lng': -117.0382,
                        'address': 'Tijuana, BC', 'radius_km': 5,
                    },
                    'expires_at': now - timedelta(hours=1),
                },
            )
            activity_blitzes[activity] = blitz

        created_logs = 0
        zone_log_counts = {}

        for zone in ZONES:
            zone_total = 0
            zone_24h = 0

            for window, counts in HEATMAP_COUNTS.items():
                n = random.randint(counts['min'], counts['max'])
                if window == 'last_24h':
                    min_h, max_h = 1, 23
                elif window == 'last_7d':
                    min_h, max_h = 25, 167
                else:
                    min_h, max_h = 169, 700

                for _ in range(n):
                    activity = random.choice(zone['activities'])
                    blitz = activity_blitzes.get(activity)
                    hours_ago = random.uniform(min_h, max_h)
                    ts = now - timedelta(hours=hours_ago)

                    log = LocationLog.objects.create(
                        blitz=blitz,
                        latitude=Decimal(str(round(_jitter(zone['lat']), 6))),
                        longitude=Decimal(str(round(_jitter(zone['lng']), 6))),
                        event_type=f'blitz_start:{activity}',
                    )
                    LocationLog.objects.filter(id=log.id).update(created_at=ts)
                    created_logs += 1
                    zone_total += 1
                    if window == 'last_24h':
                        zone_24h += 1

            zone_log_counts[zone['id']] = {'last_24h': zone_24h, 'total': zone_total}

        # ZoneStats
        today = now.date()
        created_zones = 0
        for zone in ZONES:
            c24h = zone_log_counts.get(zone['id'], {}).get('last_24h', 0)
            groups_live = max(1, c24h)
            people_count = groups_live * random.randint(2, 4)

            _, created = ZoneStats.objects.update_or_create(
                zone_id=zone['id'], stats_date=today,
                defaults={
                    'zone_name': zone['name'],
                    'center_lat': Decimal(str(zone['lat'])),
                    'center_lng': Decimal(str(zone['lng'])),
                    'groups_live': groups_live,
                    'people_count': people_count,
                    'peak_hour': zone['peak_hour'],
                    'activity_level': zone['activity_level'],
                    'hourly_trend': zone['trend'],
                },
            )
            if created:
                created_zones += 1

        self.stdout.write(self.style.SUCCESS(
            f'  Heat Map: ~{created_logs} LocationLogs, {created_zones}/{len(ZONES)} ZoneStats'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 11 — Billing
    # ═══════════════════════════════════════════════════════════════════

    def _phase_11_billing(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 11: Billing =='))

        sub_start = self.now - timedelta(days=20)

        # ── Andrea: Premium ──
        pm_andrea, _ = PaymentMethod.objects.get_or_create(
            user=self.andrea, external_id='pm_testbed_andrea_001',
            defaults={
                'provider': 'stripe', 'method_type': 'card',
                'last_four': '4242', 'card_brand': 'Visa',
                'exp_month': 12, 'exp_year': 2028,
                'billing_email': self.andrea.email,
                'is_default': True, 'is_valid': True,
            },
        )
        sub_andrea, _ = Subscription.objects.get_or_create(
            user=self.andrea, plan=self.premium_plan, status='active',
            defaults={
                'external_id': 'sub_testbed_andrea_001',
                'started_at': sub_start,
                'current_period_start': sub_start,
                'current_period_end': sub_start + timedelta(days=30),
                'default_payment_method': pm_andrea,
                'billing_cycle_count': 1,
            },
        )
        inv_andrea, _ = Invoice.objects.get_or_create(
            invoice_number='INV-TB-2026-001',
            defaults={
                'user': self.andrea, 'subscription': sub_andrea,
                'status': 'paid', 'currency': 'USD',
                'subtotal': Decimal('0.99'), 'tax': Decimal('0.16'),
                'total': Decimal('1.15'), 'amount_paid': Decimal('1.15'),
                'amount_due': Decimal('0.00'),
                'invoice_date': sub_start, 'paid_at': sub_start,
                'period_start': sub_start,
                'period_end': sub_start + timedelta(days=30),
                'billing_name': self.andrea.full_name,
                'billing_email': self.andrea.email,
            },
        )
        InvoiceItem.objects.get_or_create(
            invoice=inv_andrea, item_type='subscription',
            defaults={
                'description': 'SquadUp Premium - Mensual',
                'quantity': 1, 'unit_price': Decimal('0.99'),
                'amount': Decimal('0.99'), 'plan': self.premium_plan,
                'period_start': sub_start,
                'period_end': sub_start + timedelta(days=30),
            },
        )
        Payment.objects.get_or_create(
            invoice=inv_andrea, external_id='pi_testbed_andrea_001',
            defaults={
                'payment_method': pm_andrea, 'provider': 'stripe',
                'status': 'succeeded', 'currency': 'USD',
                'amount': Decimal('1.15'), 'processed_at': sub_start,
            },
        )

        # ── Mateo: Premium ──
        pm_mateo, _ = PaymentMethod.objects.get_or_create(
            user=self.mateo, external_id='pm_testbed_mateo_001',
            defaults={
                'provider': 'stripe', 'method_type': 'card',
                'last_four': '5555', 'card_brand': 'Mastercard',
                'exp_month': 6, 'exp_year': 2027,
                'billing_email': self.mateo.email,
                'is_default': True, 'is_valid': True,
            },
        )
        sub_mateo, _ = Subscription.objects.get_or_create(
            user=self.mateo, plan=self.premium_plan, status='active',
            defaults={
                'external_id': 'sub_testbed_mateo_001',
                'started_at': sub_start,
                'current_period_start': sub_start,
                'current_period_end': sub_start + timedelta(days=30),
                'default_payment_method': pm_mateo,
                'billing_cycle_count': 1,
            },
        )
        inv_mateo, _ = Invoice.objects.get_or_create(
            invoice_number='INV-TB-2026-002',
            defaults={
                'user': self.mateo, 'subscription': sub_mateo,
                'status': 'paid', 'currency': 'USD',
                'subtotal': Decimal('0.99'), 'tax': Decimal('0.16'),
                'total': Decimal('1.15'), 'amount_paid': Decimal('1.15'),
                'amount_due': Decimal('0.00'),
                'invoice_date': sub_start, 'paid_at': sub_start,
                'period_start': sub_start,
                'period_end': sub_start + timedelta(days=30),
                'billing_name': self.mateo.full_name,
                'billing_email': self.mateo.email,
            },
        )
        InvoiceItem.objects.get_or_create(
            invoice=inv_mateo, item_type='subscription',
            defaults={
                'description': 'SquadUp Premium - Mensual',
                'quantity': 1, 'unit_price': Decimal('0.99'),
                'amount': Decimal('0.99'), 'plan': self.premium_plan,
                'period_start': sub_start,
                'period_end': sub_start + timedelta(days=30),
            },
        )
        Payment.objects.get_or_create(
            invoice=inv_mateo, external_id='pi_testbed_mateo_001',
            defaults={
                'payment_method': pm_mateo, 'provider': 'stripe',
                'status': 'succeeded', 'currency': 'USD',
                'amount': Decimal('1.15'), 'processed_at': sub_start,
            },
        )

        # ── Carlos: Free ──
        Subscription.objects.get_or_create(
            user=self.carlos, plan=self.free_plan,
            defaults={
                'status': 'active',
                'started_at': self.now - timedelta(days=28),
                'current_period_start': self.now - timedelta(days=28),
                'current_period_end': self.now + timedelta(days=36500),
            },
        )

        # ── Sofía: Free ──
        Subscription.objects.get_or_create(
            user=self.sofia, plan=self.free_plan,
            defaults={
                'status': 'active',
                'started_at': self.now - timedelta(days=25),
                'current_period_start': self.now - timedelta(days=25),
                'current_period_end': self.now + timedelta(days=36500),
            },
        )

        # ── Coupon ──
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

        self.stdout.write(self.style.SUCCESS(
            '  Billing: Andrea(Premium+Visa) + Mateo(Premium+MC) + Carlos(Free) + Sofía(Free)\n'
            '  Coupon: SQUADUP50 (50% off)'
        ))

    # ═══════════════════════════════════════════════════════════════════
    #  Phase 12 — Misc (DeviceTokens, Report, MatchMute)
    # ═══════════════════════════════════════════════════════════════════

    def _phase_12_misc(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n== Phase 12: Misc =='))

        # 6 DeviceTokens
        tokens = [
            (self.andrea, 'testbed_fcm_andrea_ios', 'ios', 'iPhone-16e'),
            (self.andrea, 'testbed_fcm_andrea_web', 'web', ''),
            (self.carlos, 'testbed_fcm_carlos_android', 'android', 'Pixel-8'),
            (self.sofia, 'testbed_fcm_sofia_ios', 'ios', 'iPhone-15'),
            (self.mateo, 'testbed_fcm_mateo_android', 'android', 'Galaxy-S24'),
            (self.mateo, 'testbed_fcm_mateo_web', 'web', ''),
        ]
        for user, token, platform, device_id in tokens:
            DeviceToken.objects.get_or_create(
                token=token,
                defaults={
                    'user': user, 'platform': platform,
                    'device_id': device_id, 'is_active': True,
                },
            )
        self.stdout.write(self.style.SUCCESS('  DeviceTokens: 6'))

        # 1 Report (Andrea reported Carlos for spam)
        Report.objects.get_or_create(
            reporter=self.andrea,
            report_type='user',
            target_id=self.carlos.id,
            defaults={
                'reason': 'spam',
                'description': 'Envía mensajes no deseados repetidamente.',
                'status': 'pending',
            },
        )
        self.stdout.write(self.style.SUCCESS('  Report: 1 (Andrea -> Carlos, spam)'))

        # 1 MatchMute (Carlos muted the active match)
        MatchMute.objects.get_or_create(
            user=self.carlos,
            match=self.match_active,
        )
        self.stdout.write(self.style.SUCCESS('  MatchMute: 1 (Carlos muted active match)'))

    # ═══════════════════════════════════════════════════════════════════
    #  Summary
    # ═══════════════════════════════════════════════════════════════════

    def _print_summary(self):
        self.stdout.write(self.style.MIGRATE_HEADING('\n' + '=' * 60))
        self.stdout.write(self.style.SUCCESS('  TESTBED SEED COMPLETE'))
        self.stdout.write('=' * 60)
        self.stdout.write(f'''
  Firebase login: {'REAL (use email/password below)' if not self.skip_firebase else 'SKIPPED (fake UIDs)'}

  Loginable Users:
    Andrea Salazar   andrea@squadup.test  SquadUp2026!  Premium  (Blitz leader, most connections)
    Carlos Mendoza   carlos@squadup.test  SquadUp2026!  Free     (Democratic voter, gets reported)
    Sofia Luna       sofia@squadup.test   SquadUp2026!  Free     (Solo mode active)
    Mateo Rivera     mateo@squadup.test   SquadUp2026!  Premium  (Expired/cancelled states)

  + 16 NPC users (fake UIDs, for discoverable content)

  Data counts:
    Users:              {User.objects.count()}
    Profiles:           {Profile.objects.count()}
    ProfilePhotos:      {ProfilePhoto.objects.count()}
    Friendships:        {Friendship.objects.count()}
    Groups:             {Group.objects.count()}
    GroupMemberships:   {GroupMembership.objects.count()}
    Blitzes:            {Blitz.objects.count()}
    BlitzInteractions:  {BlitzInteraction.objects.count()}
    BlitzVotes:         {BlitzVote.objects.count()}
    Matches:            {Match.objects.count()}
    Chats:              {Chat.objects.count()}
    Messages:           {Message.objects.count()}
    MatchActivities:    {MatchActivity.objects.count()}
    MeetupPlans:        {MeetupPlan.objects.count()}
    Memories:           {Memory.objects.count()}
    MemoryPhotos:       {MemoryPhoto.objects.count()}
    SoloMatches:        {SoloMatch.objects.count()}
    SoloCoordinations:  {SoloCoordination.objects.count()}
    Notifications:      {Notification.objects.count()}
    DeviceTokens:       {DeviceToken.objects.count()}
    LocationLogs:       {LocationLog.objects.count()}
    ZoneStats:          {ZoneStats.objects.count()}
    Plans:              {Plan.objects.count()}
    Subscriptions:      {Subscription.objects.count()}
    PaymentMethods:     {PaymentMethod.objects.count()}
    Invoices:           {Invoice.objects.count()}
    Payments:           {Payment.objects.count()}
    Coupons:            {Coupon.objects.count()}
    Reports:            {Report.objects.count()}
    MatchMutes:         {MatchMute.objects.count()}

  Test scenarios:
    Blitz:         active-leader, active-democratic, 2x matched, expired, cancelled
    Discoverable:  10 NPC active blitzes for Andrea to swipe in leader mode
                   16 NPC users with profiles for solo mode discovery
    Received:      3 NPC groups already liked Andrea's active blitzes
    Historical:    5 NPC-vs-NPC matches (past area activity)
    Interactions:  mutual likes, democratic consensus (3 votes), one-way like, skip
    Group Match:   1 active with chat(8 msgs), 3 activities, 1 meetup plan
    Solo Mode:     matched, coordinating, pending, started, expired, cancelled
    Coordinations: both_ready, waiting, started
    Notifications: all 13 types across 4 users (mix read/unread)
    Heat Map:      10 zones, ~60 LocationLogs, 10 ZoneStats
    Billing:       2 Premium + 2 Free + 16 NPC Free, 2 payment methods, 2 invoices, SQUADUP50 coupon
    Misc:          6 device tokens, 1 report, 1 match mute
''')
