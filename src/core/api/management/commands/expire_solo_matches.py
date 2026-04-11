"""
Management command to expire timed-out solo matches and coordinations.
Run via cron or celery-beat every 5 minutes.

Usage:
    python manage.py expire_solo_matches
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import SoloMatch, SoloCoordination

logger = logging.getLogger('api')


class Command(BaseCommand):
    help = 'Expire timed-out solo matches and coordinations'

    def handle(self, *args, **options):
        now = timezone.now()

        # Expire pending solo matches past their expiry
        pending_expired = SoloMatch.objects.filter(
            status='pending',
            expires_at__lt=now,
        ).update(status='expired')

        # Expire waiting coordinations past their expiry
        coord_expired = SoloCoordination.objects.filter(
            status='waiting',
            expires_at__lt=now,
        ).update(status='expired')

        # Also expire parent SoloMatch for expired coordinations
        parent_expired = SoloMatch.objects.filter(
            coordination__status='expired',
            status__in=['matched', 'coordinating', 'ready'],
        ).update(status='expired')

        total = pending_expired + coord_expired + parent_expired
        if total > 0:
            logger.info(
                f"expire_solo_matches: {pending_expired} pending, "
                f"{coord_expired} coordinations, {parent_expired} parent matches expired"
            )
            self.stdout.write(
                self.style.SUCCESS(f'Expired {total} solo matches/coordinations')
            )
        else:
            self.stdout.write('No expired solo matches found')
