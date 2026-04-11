"""
SquadUp - Stripe Payment Service
================================
Handles Stripe Checkout sessions, webhook processing, and subscription management.

Usage:
    from utils.stripe_service import StripeService

    # Create checkout session
    session = StripeService.create_checkout_session(
        user=request.user,
        price_cents=99,
        success_url='squadup://subscription/success',
        cancel_url='squadup://subscription/cancel',
    )

    # Handle webhook
    event = StripeService.verify_webhook(payload, signature)
"""

import logging
from datetime import timedelta
from decimal import Decimal

import stripe
from django.conf import settings
from django.utils import timezone

from api.models import (
    Plan, Subscription, PaymentMethod, Invoice, InvoiceItem,
    Payment, WebhookLog, User
)

logger = logging.getLogger('api')

# Initialize Stripe with API key
stripe.api_key = settings.STRIPE_SECRET_KEY


class StripeService:
    """
    Service for Stripe payment operations.
    """

    # Premium plan configuration
    PREMIUM_PRICE_CENTS = 99  # $0.99/month
    TRIAL_DAYS = 7

    @staticmethod
    def create_checkout_session(
        user: User,
        success_url: str,
        cancel_url: str,
        price_cents: int = None,
        trial_days: int = None,
    ) -> dict:
        """
        Create a Stripe Checkout session for subscription.

        Returns dict with:
        - checkout_url: URL to redirect user to
        - session_id: Stripe session ID
        """
        if price_cents is None:
            price_cents = StripeService.PREMIUM_PRICE_CENTS
        if trial_days is None:
            trial_days = StripeService.TRIAL_DAYS

        try:
            # Get or create Stripe customer
            customer_id = StripeService._get_or_create_customer(user)

            session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': 'SquadUp Premium',
                            'description': 'Unlimited Blitz sessions, premium analytics, and more',
                        },
                        'unit_amount': price_cents,
                        'recurring': {
                            'interval': 'month',
                        },
                    },
                    'quantity': 1,
                }],
                mode='subscription',
                subscription_data={
                    'trial_period_days': trial_days,
                    'metadata': {
                        'user_id': str(user.id),
                    },
                },
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_id': str(user.id),
                },
                client_reference_id=str(user.id),
            )

            logger.info(f"[STRIPE] Created checkout session {session.id} for user {user.id}")

            return {
                'checkout_url': session.url,
                'session_id': session.id,
            }

        except stripe.error.StripeError as e:
            logger.error(f"[STRIPE] Error creating checkout session: {str(e)}")
            raise

    @staticmethod
    def _get_or_create_customer(user: User) -> str:
        """
        Get existing Stripe customer ID or create new customer.
        """
        # Check if user has a payment method with Stripe customer ID
        existing_pm = user.payment_methods.filter(
            provider='stripe'
        ).first()

        if existing_pm and existing_pm.metadata.get('stripe_customer_id'):
            return existing_pm.metadata['stripe_customer_id']

        # Check subscription for customer ID
        existing_sub = user.subscriptions.filter(
            external_id__isnull=False
        ).first()

        if existing_sub and existing_sub.metadata.get('stripe_customer_id'):
            return existing_sub.metadata['stripe_customer_id']

        # Create new Stripe customer
        customer = stripe.Customer.create(
            email=user.email,
            name=f"{user.first_name} {user.last_name}",
            metadata={
                'user_id': str(user.id),
            },
        )

        logger.info(f"[STRIPE] Created customer {customer.id} for user {user.id}")
        return customer.id

    @staticmethod
    def verify_webhook(payload: bytes, signature: str) -> stripe.Event:
        """
        Verify and parse a Stripe webhook event.

        Raises stripe.error.SignatureVerificationError if invalid.
        """
        return stripe.Webhook.construct_event(
            payload,
            signature,
            settings.STRIPE_WEBHOOK_SECRET,
        )

    @staticmethod
    def handle_checkout_completed(session: dict) -> Subscription:
        """
        Handle checkout.session.completed event.
        Creates subscription record and activates premium for user.
        """
        user_id = session.get('client_reference_id') or session.get('metadata', {}).get('user_id')
        if not user_id:
            raise ValueError("No user_id in session metadata")

        user = User.objects.get(id=int(user_id))
        subscription_id = session.get('subscription')
        customer_id = session.get('customer')

        # Get or create Premium plan (use 'premium' slug to match seeded PlanFeatures)
        premium_plan, _ = Plan.objects.get_or_create(
            slug='premium',
            defaults={
                'name': 'Premium',
                'description': 'Unlimited Blitz sessions, premium analytics, and more',
                'plan_type': 'premium',
                'price': Decimal('9.99'),
                'currency': 'USD',
                'billing_interval': 'monthly',
                'trial_days': StripeService.TRIAL_DAYS,
                'is_active': True,
                'is_public': True,
            }
        )

        # Cancel any existing active subscriptions
        user.subscriptions.filter(
            status__in=['trialing', 'active', 'past_due']
        ).update(
            status='canceled',
            canceled_at=timezone.now(),
            cancel_reason='upgraded',
        )

        # Retrieve subscription from Stripe to get dates
        stripe_sub = stripe.Subscription.retrieve(subscription_id)

        now = timezone.now()
        trial_end = None
        status = 'active'

        if stripe_sub.trial_end:
            from datetime import datetime
            trial_end = datetime.fromtimestamp(stripe_sub.trial_end, tz=timezone.utc)
            status = 'trialing'

        period_end = now + timedelta(days=30)
        if stripe_sub.current_period_end:
            from datetime import datetime
            period_end = datetime.fromtimestamp(stripe_sub.current_period_end, tz=timezone.utc)

        # Create subscription record
        subscription = Subscription.objects.create(
            user=user,
            plan=premium_plan,
            external_id=subscription_id,
            status=status,
            started_at=now,
            current_period_start=now,
            current_period_end=period_end,
            trial_start=now if trial_end else None,
            trial_end=trial_end,
            metadata={
                'stripe_customer_id': customer_id,
                'stripe_subscription_id': subscription_id,
            },
        )

        logger.info(
            f"[STRIPE] Created subscription {subscription.id} for user {user.id} "
            f"(status: {status}, trial_end: {trial_end})"
        )

        return subscription

    @staticmethod
    def handle_invoice_paid(invoice: dict) -> None:
        """
        Handle invoice.paid event.
        Updates subscription period and creates invoice record.
        """
        subscription_id = invoice.get('subscription')
        if not subscription_id:
            return

        try:
            subscription = Subscription.objects.get(external_id=subscription_id)
        except Subscription.DoesNotExist:
            logger.warning(f"[STRIPE] Subscription not found for invoice: {subscription_id}")
            return

        # Update subscription status and period
        stripe_sub = stripe.Subscription.retrieve(subscription_id)

        from datetime import datetime
        period_start = datetime.fromtimestamp(
            stripe_sub.current_period_start, tz=timezone.utc
        )
        period_end = datetime.fromtimestamp(
            stripe_sub.current_period_end, tz=timezone.utc
        )

        subscription.status = 'active'
        subscription.current_period_start = period_start
        subscription.current_period_end = period_end
        subscription.billing_cycle_count += 1
        subscription.save()

        # Create invoice record
        amount_paid = invoice.get('amount_paid', 0) / 100  # cents to dollars
        Invoice.objects.create(
            invoice_number=f"INV-{invoice.get('id', '')[:8]}",
            user=subscription.user,
            subscription=subscription,
            external_id=invoice.get('id'),
            status='paid',
            currency='USD',
            subtotal=Decimal(str(amount_paid)),
            total=Decimal(str(amount_paid)),
            amount_paid=Decimal(str(amount_paid)),
            amount_due=Decimal('0.00'),
            invoice_date=timezone.now(),
            paid_at=timezone.now(),
            period_start=period_start,
            period_end=period_end,
        )

        logger.info(f"[STRIPE] Invoice paid for subscription {subscription.id}")

    @staticmethod
    def handle_invoice_payment_failed(invoice: dict) -> None:
        """
        Handle invoice.payment_failed event.
        Sets subscription to past_due with grace period.
        """
        subscription_id = invoice.get('subscription')
        if not subscription_id:
            return

        try:
            subscription = Subscription.objects.get(external_id=subscription_id)
        except Subscription.DoesNotExist:
            return

        subscription.status = 'past_due'
        subscription.grace_period_end = timezone.now() + timedelta(days=7)
        subscription.save()

        logger.warning(f"[STRIPE] Payment failed for subscription {subscription.id}")

    @staticmethod
    def handle_subscription_deleted(stripe_subscription: dict) -> None:
        """
        Handle customer.subscription.deleted event.
        Cancels the subscription and downgrades user to free.
        """
        subscription_id = stripe_subscription.get('id')

        try:
            subscription = Subscription.objects.get(external_id=subscription_id)
        except Subscription.DoesNotExist:
            return

        subscription.status = 'canceled'
        subscription.canceled_at = timezone.now()
        subscription.cancel_reason = 'user_request'
        subscription.save()

        # Create free subscription
        free_plan, _ = Plan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Free',
                'plan_type': 'free',
                'price': Decimal('0.00'),
                'billing_interval': 'monthly',
            }
        )

        now = timezone.now()
        Subscription.objects.create(
            user=subscription.user,
            plan=free_plan,
            status='active',
            started_at=now,
            current_period_start=now,
            current_period_end=now + timedelta(days=36500),
        )

        logger.info(f"[STRIPE] Subscription {subscription.id} canceled, user downgraded to free")

    @staticmethod
    def reactivate_subscription(subscription: Subscription) -> None:
        """
        Undo a pending cancellation by clearing cancel_at_period_end in Stripe.
        Only works when the subscription hasn't actually been canceled yet.
        """
        if not subscription.external_id:
            return

        try:
            stripe.Subscription.modify(
                subscription.external_id,
                cancel_at_period_end=False,
            )

            logger.info(f"[STRIPE] Subscription {subscription.id} reactivated")

        except stripe.error.StripeError as e:
            logger.error(f"[STRIPE] Error reactivating subscription: {str(e)}")
            raise

    @staticmethod
    def cancel_subscription(subscription: Subscription, immediate: bool = False) -> None:
        """
        Cancel a subscription in Stripe.

        Args:
            subscription: The subscription to cancel
            immediate: If True, cancel immediately. If False, cancel at period end.
        """
        if not subscription.external_id:
            return

        try:
            if immediate:
                stripe.Subscription.cancel(subscription.external_id)
            else:
                stripe.Subscription.modify(
                    subscription.external_id,
                    cancel_at_period_end=True,
                )

            logger.info(f"[STRIPE] Subscription {subscription.id} cancellation requested")

        except stripe.error.StripeError as e:
            logger.error(f"[STRIPE] Error canceling subscription: {str(e)}")
            raise
