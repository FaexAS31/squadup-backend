import logging
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle
from api.models import Subscription
from api.Serializers.subscription_serializer import SubscriptionSerializer
from utils.stripe_service import StripeService
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

logger = logging.getLogger('api')

@extend_schema(tags=['Subscriptions'])
class SubscriptionViewSet(viewsets.ModelViewSet):
    """
    ViewSet para Subscriptions.
    Logging: create, update, destroy (CRÍTICO - todas las operaciones de billing)
    """
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    throttle_classes = [AnonRateThrottle, UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'fuerza_bruta'

    @extend_schema(
        summary="Create Stripe Checkout Session",
        description="Creates a Stripe Checkout session for Premium subscription ($0.99/mo with 7-day trial)",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'checkout_url': {'type': 'string', 'description': 'URL to redirect user to Stripe Checkout'},
                    'session_id': {'type': 'string', 'description': 'Stripe session ID'},
                },
            },
            400: {'description': 'Invalid request'},
            500: {'description': 'Stripe API error'},
        },
    )
    @action(detail=False, methods=['post'], url_path='create-checkout')
    def create_checkout(self, request):
        """
        Create a Stripe Checkout session for Premium subscription.

        POST /api/subscriptions/create-checkout/

        Request body (optional):
        {
            "success_url": "squadup://subscription/success",
            "cancel_url": "squadup://subscription/cancel"
        }

        Returns:
        {
            "checkout_url": "https://checkout.stripe.com/...",
            "session_id": "cs_..."
        }
        """
        user = request.user

        # Check if user already has premium
        if user.is_premium:
            return Response(
                {'error': 'You already have an active Premium subscription'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get redirect URLs from request or use defaults
        success_url = request.data.get(
            'success_url',
            'squadup://subscription/success'
        )
        cancel_url = request.data.get(
            'cancel_url',
            'squadup://subscription/cancel'
        )

        try:
            result = StripeService.create_checkout_session(
                user=user,
                success_url=success_url,
                cancel_url=cancel_url,
            )

            logger.info(
                f"[BILLING] Checkout session created for user {user.id}: {result['session_id']}"
            )

            return Response(result)

        except Exception as e:
            logger.error(f"[BILLING] Error creating checkout session: {str(e)}")
            return Response(
                {'error': 'Failed to create checkout session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Cancel Subscription",
        description="Cancel the current Premium subscription (at period end)",
        responses={
            200: {'description': 'Subscription will be canceled at period end'},
            400: {'description': 'No active subscription'},
            500: {'description': 'Stripe API error'},
        },
    )
    @action(detail=False, methods=['post'], url_path='cancel')
    def cancel_subscription(self, request):
        """
        Cancel the user's Premium subscription.

        POST /api/subscriptions/cancel/

        Request body (optional):
        {
            "immediate": false  // true to cancel immediately, false to cancel at period end
        }
        """
        user = request.user
        subscription = user.active_subscription

        if not subscription or subscription.plan.is_free:
            return Response(
                {'error': 'No active Premium subscription to cancel'},
                status=status.HTTP_400_BAD_REQUEST
            )

        immediate = request.data.get('immediate', False)

        try:
            StripeService.cancel_subscription(subscription, immediate=immediate)

            if immediate:
                subscription.status = 'canceled'
                subscription.canceled_at = timezone.now()
            else:
                subscription.cancel_at_period_end = True

            subscription.cancel_reason = 'user_request'
            subscription.save()

            logger.info(
                f"[BILLING] Subscription {subscription.id} cancellation requested "
                f"(immediate={immediate}) by user {user.id}"
            )

            return Response({
                'message': 'Subscription will be canceled' + (
                    ' immediately' if immediate else ' at the end of the billing period'
                ),
                'cancel_at_period_end': not immediate,
            })

        except Exception as e:
            logger.error(f"[BILLING] Error canceling subscription: {str(e)}")
            return Response(
                {'error': 'Failed to cancel subscription'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Reactivate Subscription",
        description="Undo a pending cancellation and keep the Premium subscription active",
        responses={
            200: {'description': 'Cancellation reversed, subscription will renew'},
            400: {'description': 'No pending cancellation to undo'},
            500: {'description': 'Stripe API error'},
        },
    )
    @action(detail=False, methods=['post'], url_path='reactivate')
    def reactivate_subscription(self, request):
        """
        Undo a scheduled cancellation.

        POST /api/subscriptions/reactivate/
        """
        user = request.user
        subscription = user.active_subscription

        if not subscription or not subscription.cancel_at_period_end:
            return Response(
                {'error': 'No pending cancellation to undo'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            StripeService.reactivate_subscription(subscription)

            subscription.cancel_at_period_end = False
            subscription.cancel_reason = ''
            subscription.save()

            logger.info(
                f"[BILLING] Subscription {subscription.id} reactivated by user {user.id}"
            )

            return Response({
                'message': 'Subscription reactivated — your Premium will renew as usual',
                'cancel_at_period_end': False,
            })

        except Exception as e:
            logger.error(f"[BILLING] Error reactivating subscription: {str(e)}")
            return Response(
                {'error': 'Failed to reactivate subscription'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary="Get Current Subscription Status",
        description="Get the current user's subscription status and plan details",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'has_subscription': {'type': 'boolean'},
                    'is_premium': {'type': 'boolean'},
                    'is_trialing': {'type': 'boolean'},
                    'plan': {'type': 'string'},
                    'status': {'type': 'string'},
                    'trial_end': {'type': 'string', 'format': 'date-time', 'nullable': True},
                    'current_period_end': {'type': 'string', 'format': 'date-time', 'nullable': True},
                    'cancel_at_period_end': {'type': 'boolean'},
                },
            },
        },
    )
    @action(detail=False, methods=['get'], url_path='status', throttle_classes=[UserRateThrottle])
    def subscription_status(self, request):
        """
        Get the current user's subscription status.

        GET /api/subscriptions/status/
        """
        user = request.user
        subscription = user.active_subscription

        return Response({
            'has_subscription': subscription is not None,
            'is_premium': user.is_premium,
            'is_trialing': user.is_trialing,
            'plan': subscription.plan.name if subscription else 'Free',
            'status': subscription.status if subscription else 'none',
            'trial_end': subscription.trial_end if subscription else None,
            'current_period_end': subscription.current_period_end if subscription else None,
            'cancel_at_period_end': subscription.cancel_at_period_end if subscription else False,
        })

    def create(self, request, *args, **kwargs):
        logger.info(
            f"[BILLING-CRITICAL] Intento de CREATE en Subscription | "
            f"Usuario: {request.user} | User_ID: {request.data.get('user')} | "
            f"Plan_ID: {request.data.get('plan')}"
        )
        try:
            response = super().create(request, *args, **kwargs)
            logger.info(
                f"[BILLING-CRITICAL] Subscription CREATE exitoso. "
                f"ID: {response.data.get('id')} | User: {response.data.get('user')} | "
                f"Plan: {response.data.get('plan')} | Status: {response.data.get('status')}"
            )
            return response
        except Exception as e:
            logger.error(f"[BILLING-CRITICAL] Error en CREATE de Subscription: {str(e)}")
            raise e

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_status = instance.status
        old_plan = instance.plan_id
        logger.info(
            f"[BILLING-CRITICAL] Intento de UPDATE en Subscription | "
            f"Usuario: {request.user} | ID: {instance.id} | "
            f"Status actual: {old_status} | Plan actual: {old_plan} | "
            f"Campos modificados: {list(request.data.keys())}"
        )
        try:
            response = super().update(request, *args, **kwargs)
            logger.info(
                f"[BILLING-CRITICAL] Subscription UPDATE exitoso. ID: {response.data.get('id')} | "
                f"Status: {old_status} → {response.data.get('status')} | "
                f"Plan: {old_plan} → {response.data.get('plan')}"
            )
            return response
        except Exception as e:
            logger.error(
                f"[BILLING-CRITICAL] Error en UPDATE de Subscription ID={instance.id}: {str(e)}"
            )
            raise e

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        logger.warning(
            f"[BILLING-CRITICAL] Intento de DESTROY en Subscription | "
            f"Usuario: {request.user} | ID: {instance.id} | "
            f"User: {instance.user_id} | Plan: {instance.plan_id} | "
            f"Status: {instance.status}"
        )
        try:
            response = super().destroy(request, *args, **kwargs)
            logger.warning(
                f"[BILLING-CRITICAL] Subscription DESTROY exitoso. ID: {instance.id}"
            )
            return response
        except Exception as e:
            logger.error(
                f"[BILLING-CRITICAL] Error en DESTROY de Subscription ID={instance.id}: {str(e)}"
            )
            raise e
