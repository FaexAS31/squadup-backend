"""
Stripe Webhook Handler
======================
Handles incoming webhook events from Stripe.

Endpoint: POST /api/stripe/webhook/
"""

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import stripe

from api.models import WebhookLog
from utils.stripe_service import StripeService

logger = logging.getLogger('api')


@api_view(['POST'])
@authentication_classes([])  # No authentication required for webhooks
@permission_classes([AllowAny])  # Stripe doesn't authenticate with Firebase
def stripe_webhook(request):
    """
    Handle Stripe webhook events.

    Supported events:
    - checkout.session.completed: User completed checkout
    - invoice.paid: Subscription payment succeeded
    - invoice.payment_failed: Subscription payment failed
    - customer.subscription.deleted: Subscription was canceled
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    # Verify webhook signature
    try:
        event = StripeService.verify_webhook(payload, sig_header)
    except ValueError:
        logger.error("[STRIPE WEBHOOK] Invalid payload")
        return Response({'error': 'Invalid payload'}, status=status.HTTP_400_BAD_REQUEST)
    except stripe.error.SignatureVerificationError:
        logger.error("[STRIPE WEBHOOK] Invalid signature")
        return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

    event_id = event.get('id', 'unknown')
    event_type = event.get('type', 'unknown')

    # Check for duplicate events
    if WebhookLog.objects.filter(event_id=event_id).exists():
        logger.info(f"[STRIPE WEBHOOK] Duplicate event ignored: {event_id}")
        return Response({'status': 'already_processed'})

    # Log the webhook
    webhook_log = WebhookLog.objects.create(
        provider='stripe',
        event_id=event_id,
        event_type=event_type,
        payload=event,
        headers=dict(request.META),
        status='processing',
    )

    try:
        # Handle the event
        if event_type == 'checkout.session.completed':
            session = event['data']['object']
            StripeService.handle_checkout_completed(session)
            logger.info(f"[STRIPE WEBHOOK] checkout.session.completed processed: {event_id}")

        elif event_type == 'invoice.paid':
            invoice = event['data']['object']
            StripeService.handle_invoice_paid(invoice)
            logger.info(f"[STRIPE WEBHOOK] invoice.paid processed: {event_id}")

        elif event_type == 'invoice.payment_failed':
            invoice = event['data']['object']
            StripeService.handle_invoice_payment_failed(invoice)
            logger.info(f"[STRIPE WEBHOOK] invoice.payment_failed processed: {event_id}")

        elif event_type == 'customer.subscription.deleted':
            subscription = event['data']['object']
            StripeService.handle_subscription_deleted(subscription)
            logger.info(f"[STRIPE WEBHOOK] customer.subscription.deleted processed: {event_id}")

        else:
            # Log unhandled events but don't fail
            logger.info(f"[STRIPE WEBHOOK] Unhandled event type: {event_type}")
            webhook_log.status = 'ignored'
            webhook_log.save()
            return Response({'status': 'ignored'})

        # Mark as processed
        webhook_log.status = 'processed'
        webhook_log.processed_at = timezone.now()
        webhook_log.save()

        return Response({'status': 'success'})

    except Exception as e:
        logger.error(f"[STRIPE WEBHOOK] Error processing {event_type}: {str(e)}")
        webhook_log.status = 'failed'
        webhook_log.error_message = str(e)
        webhook_log.processing_attempts += 1
        webhook_log.save()

        # Return 500 so Stripe will retry
        return Response(
            {'error': 'Processing failed'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
