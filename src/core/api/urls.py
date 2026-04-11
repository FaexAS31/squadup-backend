from django.urls import path, include
from rest_framework.routers import DefaultRouter
from api import Viewsets
from api.Viewsets.stripe_webhook_viewset import stripe_webhook
from utils.router_utils import register_all_viewsets

router = DefaultRouter()

register_all_viewsets(router, Viewsets)

urlpatterns = [
    path("", include(router.urls)),
    path("stripe/webhook/", stripe_webhook, name='stripe-webhook'),
]