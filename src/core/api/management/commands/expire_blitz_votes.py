"""
Management command to expire pending blitz votes on expired blitz sessions.
Run via cron alongside expire_solo_matches every 5 minutes.

Usage:
    python manage.py expire_blitz_votes
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import BlitzVote

logger = logging.getLogger('api')


class Command(BaseCommand):
    help = 'Expire pending blitz votes on expired blitz sessions'

    def handle(self, *args, **options):
        now = timezone.now()

        expired_count = BlitzVote.objects.filter(
            vote='pending',
            interaction__from_blitz__expires_at__lt=now,
        ).update(vote='rejected', voted_at=now)

        if expired_count > 0:
            logger.info(f"expire_blitz_votes: {expired_count} pending votes expired")
            self.stdout.write(
                self.style.SUCCESS(f'Expired {expired_count} pending blitz votes')
            )
        else:
            self.stdout.write('No expired blitz votes found')
