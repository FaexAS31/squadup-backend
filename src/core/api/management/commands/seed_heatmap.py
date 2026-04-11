"""
Seed realistic heat map data for Tijuana area.

Creates LocationLog entries spread across 24h / 7d / 30d windows so each
time-range filter on the frontend shows progressively more data.  Also
creates matching ZoneStats records.

Usage:
    python manage.py seed_heatmap          # default behaviour
    python manage.py seed_heatmap --clear  # wipe existing data first
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import Blitz, Group, LocationLog, User, ZoneStats


# ── Tijuana neighborhoods with real coordinates ──────────────────────
ZONES = [
    {
        'id': 'tj_zona_rio',
        'name': 'Zona Rio',
        'lat': 32.5215,
        'lng': -117.0115,
        'activity_level': 'high',
        'peak_hour': 20,
        'trend': {'6pm': 3, '7pm': 5, '8pm': 8, '9pm': 6, '10pm': 4},
        'activities': ['food', 'drinks', 'coffee'],
    },
    {
        'id': 'tj_playas',
        'name': 'Playas de Tijuana',
        'lat': 32.5290,
        'lng': -117.1200,
        'activity_level': 'medium',
        'peak_hour': 16,
        'trend': {'2pm': 2, '3pm': 4, '4pm': 5, '5pm': 4, '6pm': 3},
        'activities': ['outdoors', 'sports', 'chill'],
    },
    {
        'id': 'tj_centro',
        'name': 'Centro',
        'lat': 32.5300,
        'lng': -117.0183,
        'activity_level': 'high',
        'peak_hour': 21,
        'trend': {'7pm': 4, '8pm': 6, '9pm': 8, '10pm': 7, '11pm': 5, '12am': 2},
        'activities': ['party', 'drinks', 'music'],
    },
    {
        'id': 'tj_la_cacho',
        'name': 'La Cacho',
        'lat': 32.5198,
        'lng': -117.0289,
        'activity_level': 'medium',
        'peak_hour': 19,
        'trend': {'5pm': 2, '6pm': 3, '7pm': 5, '8pm': 4, '9pm': 3},
        'activities': ['food', 'coffee', 'explore'],
    },
    {
        'id': 'tj_gastronomica',
        'name': 'Zona Gastronomica',
        'lat': 32.5156,
        'lng': -117.0107,
        'activity_level': 'high',
        'peak_hour': 14,
        'trend': {'12pm': 3, '1pm': 5, '2pm': 7, '3pm': 5, '4pm': 3},
        'activities': ['food', 'coffee', 'drinks'],
    },
    {
        'id': 'tj_otay',
        'name': 'Otay',
        'lat': 32.5523,
        'lng': -116.9711,
        'activity_level': 'low',
        'peak_hour': 17,
        'trend': {'4pm': 1, '5pm': 3, '6pm': 2, '7pm': 1},
        'activities': ['explore', 'fitness', 'sports'],
    },
    {
        'id': 'tj_hipodromo',
        'name': 'Hipodromo',
        'lat': 32.5102,
        'lng': -117.0362,
        'activity_level': 'medium',
        'peak_hour': 8,
        'trend': {'6am': 2, '7am': 4, '8am': 5, '9am': 3, '5pm': 3, '6pm': 4},
        'activities': ['fitness', 'outdoors', 'chill'],
    },
    {
        'id': 'tj_revolucion',
        'name': 'Av. Revolucion',
        'lat': 32.5300,
        'lng': -117.0230,
        'activity_level': 'high',
        'peak_hour': 22,
        'trend': {'8pm': 3, '9pm': 5, '10pm': 7, '11pm': 6, '12am': 4},
        'activities': ['party', 'drinks', 'music'],
    },
    {
        'id': 'tj_chapultepec',
        'name': 'Chapultepec',
        'lat': 32.5178,
        'lng': -117.0205,
        'activity_level': 'medium',
        'peak_hour': 15,
        'trend': {'12pm': 2, '1pm': 3, '2pm': 4, '3pm': 4, '4pm': 3},
        'activities': ['study', 'coffee', 'gaming'],
    },
    {
        'id': 'tj_agua_caliente',
        'name': 'Agua Caliente',
        'lat': 32.5070,
        'lng': -117.0120,
        'activity_level': 'low',
        'peak_hour': 18,
        'trend': {'5pm': 2, '6pm': 3, '7pm': 2},
        'activities': ['gaming', 'chill', 'food'],
    },
]

# How many location-log clusters to create per zone, per time window
COUNTS = {
    'last_24h': {'min': 4, 'max': 8},   # recent: lots of points
    'last_7d': {'min': 3, 'max': 6},     # medium: moderate
    'last_30d': {'min': 2, 'max': 5},    # old: sparse
}


def _jitter(base, spread=0.003):
    """Add small random offset to a coordinate."""
    return float(base) + random.uniform(-spread, spread)


class Command(BaseCommand):
    help = 'Seed realistic heat-map data (LocationLogs + ZoneStats) for Tijuana'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete existing LocationLog + ZoneStats before seeding',
        )

    def handle(self, *args, **options):
        if options['clear']:
            deleted_ll = LocationLog.objects.all().delete()[0]
            deleted_zs = ZoneStats.objects.all().delete()[0]
            self.stdout.write(f'  Cleared {deleted_ll} LocationLogs, {deleted_zs} ZoneStats')

        user = User.objects.first()
        if not user:
            self.stderr.write(self.style.ERROR('No users in DB. Run populate_test_data first.'))
            return

        group = Group.objects.first()
        if not group:
            self.stderr.write(self.style.ERROR('No groups in DB. Run populate_test_data first.'))
            return

        now = timezone.now()
        created_logs = 0
        created_blitzes = []

        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Seeding Heat Map Data (Tijuana) ===\n'))

        # ── Create Blitz sessions for each activity type ─────────────
        all_activities = sorted({act for z in ZONES for act in z['activities']})
        for activity in all_activities:
            blitz, _ = Blitz.objects.get_or_create(
                group=group,
                leader=user,
                activity_type=activity,
                status='expired',
                defaults={
                    'location': {
                        'lat': 32.5149,
                        'lng': -117.0382,
                        'address': 'Tijuana, BC',
                        'radius_km': 5,
                    },
                    'expires_at': now - timedelta(hours=1),
                },
            )
            created_blitzes.append(blitz)

        activity_blitz_map = {b.activity_type: b for b in created_blitzes}
        self.stdout.write(f'  Blitz sessions: {len(created_blitzes)} activities')

        # ── Create LocationLog entries per zone per time window ──────
        zone_log_counts = {}  # zone_id -> { 'last_24h': N, 'total': N }
        for zone in ZONES:
            zone_total = 0
            zone_24h = 0

            for window, counts in COUNTS.items():
                n = random.randint(counts['min'], counts['max'])

                # Determine time offset range for this window
                if window == 'last_24h':
                    min_hours, max_hours = 1, 23
                elif window == 'last_7d':
                    min_hours, max_hours = 25, 167
                else:
                    min_hours, max_hours = 169, 700

                for _ in range(n):
                    activity = random.choice(zone['activities'])
                    blitz = activity_blitz_map.get(activity, created_blitzes[0])
                    hours_ago = random.uniform(min_hours, max_hours)
                    ts = now - timedelta(hours=hours_ago)

                    log = LocationLog.objects.create(
                        blitz=blitz,
                        latitude=Decimal(str(round(_jitter(zone['lat']), 6))),
                        longitude=Decimal(str(round(_jitter(zone['lng']), 6))),
                        event_type=f'blitz_start:{activity}',
                    )
                    # Override auto_now_add timestamp
                    LocationLog.objects.filter(id=log.id).update(created_at=ts)
                    created_logs += 1
                    zone_total += 1
                    if window == 'last_24h':
                        zone_24h += 1

            zone_log_counts[zone['id']] = {'last_24h': zone_24h, 'total': zone_total}
            self.stdout.write(f'  {zone["name"]}: {zone_total} logs ({zone_24h} in 24h)')

        # ── Create ZoneStats derived from actual log counts ───────
        today = now.date()
        created_zones = 0
        for zone in ZONES:
            counts_24h = zone_log_counts.get(zone['id'], {}).get('last_24h', 0)
            counts_total = zone_log_counts.get(zone['id'], {}).get('total', 0)
            # groups_live ~ distinct blitz sessions in last 24h
            groups_live = max(1, counts_24h)
            # people_count ~ 2-4 people per blitz session
            people_count = groups_live * random.randint(2, 4)

            _, created = ZoneStats.objects.update_or_create(
                zone_id=zone['id'],
                stats_date=today,
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
            f'\n  Done! {created_logs} LocationLogs, '
            f'{created_zones} new ZoneStats ({len(ZONES)} total zones)\n'
        ))
