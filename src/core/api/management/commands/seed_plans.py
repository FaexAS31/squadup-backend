"""
Seed Free & Premium plans with their PlanFeatures.
Also auto-creates a Free Subscription for users without one.

Usage:
    python manage.py seed_plans
"""

import logging
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from api.models import Plan, PlanFeature, Subscription, User

logger = logging.getLogger('api')

FREE_FEATURES = [
    ('max_groups', 'Max Groups', '3'),
    ('max_blitz_per_week', 'Max Blitz Per Week', '3'),
    ('max_swipes_per_blitz', 'Max Swipes Per Blitz', '10'),
    ('max_solo_connections', 'Max Solo Connections', '5'),
    ('advanced_filters', 'Advanced Filters', 'false'),
    ('voice_chat', 'Voice Chat', 'false'),
    ('full_heat_map', 'Full Heat Map', 'false'),
    ('detailed_stats', 'Detailed Stats', 'false'),
    ('priority_support', 'Priority Support', 'false'),
    ('blur_notifications', 'Blur Notifications', 'true'),
]

PREMIUM_FEATURES = [
    ('max_groups', 'Max Groups', 'unlimited'),
    ('max_blitz_per_week', 'Max Blitz Per Week', 'unlimited'),
    ('max_swipes_per_blitz', 'Max Swipes Per Blitz', 'unlimited'),
    ('max_solo_connections', 'Max Solo Connections', 'unlimited'),
    ('advanced_filters', 'Advanced Filters', 'true'),
    ('voice_chat', 'Voice Chat', 'true'),
    ('full_heat_map', 'Full Heat Map', 'true'),
    ('detailed_stats', 'Detailed Stats', 'true'),
    ('priority_support', 'Priority Support', 'true'),
    ('blur_notifications', 'Blur Notifications', 'false'),
]


class Command(BaseCommand):
    help = 'Seed Free & Premium plans with PlanFeatures and assign Free subscriptions'

    def handle(self, *args, **options):
        # Create/update Free plan
        free_plan, created = Plan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Free',
                'plan_type': 'free',
                'price': Decimal('0.00'),
                'billing_interval': 'monthly',
                'is_active': True,
                'is_public': True,
                'display_order': 0,
            },
        )
        action = 'Created' if created else 'Found existing'
        self.stdout.write(f'{action} Free plan (id={free_plan.id})')

        for key, name, value in FREE_FEATURES:
            _, fc = PlanFeature.objects.update_or_create(
                plan=free_plan,
                feature_key=key,
                defaults={'feature_name': name, 'value': value},
            )
            # fc is True if created, False if updated

        self.stdout.write(self.style.SUCCESS(
            f'  {len(FREE_FEATURES)} features synced for Free plan'
        ))

        # Create/update Premium plan
        premium_plan, created = Plan.objects.get_or_create(
            slug='premium',
            defaults={
                'name': 'Premium',
                'plan_type': 'premium',
                'price': Decimal('9.99'),
                'billing_interval': 'monthly',
                'is_active': True,
                'is_public': True,
                'display_order': 1,
            },
        )
        action = 'Created' if created else 'Found existing'
        self.stdout.write(f'{action} Premium plan (id={premium_plan.id})')

        for key, name, value in PREMIUM_FEATURES:
            PlanFeature.objects.update_or_create(
                plan=premium_plan,
                feature_key=key,
                defaults={'feature_name': name, 'value': value},
            )

        self.stdout.write(self.style.SUCCESS(
            f'  {len(PREMIUM_FEATURES)} features synced for Premium plan'
        ))

        # Auto-assign Free subscription to users without any active subscription
        users_without_sub = User.objects.exclude(
            subscriptions__status__in=['trialing', 'active', 'past_due'],
        )
        assigned = 0
        now = timezone.now()
        for user in users_without_sub:
            Subscription.objects.create(
                user=user,
                plan=free_plan,
                status='active',
                started_at=now,
                current_period_start=now,
                current_period_end=now + timedelta(days=36500),
            )
            assigned += 1

        self.stdout.write(self.style.SUCCESS(
            f'Assigned Free subscription to {assigned} users'
        ))
