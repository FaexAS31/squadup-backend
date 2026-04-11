"""
SquadUp - Billing Integration Helpers
=====================================
Este archivo muestra cómo integrar los modelos de billing con el User existente
y proporciona métodos útiles para el manejo del ciclo de suscripción.

IMPORTANTE: Este código asume que billing_models.py está en la misma app.
Ajustar imports según la estructura real del proyecto.
"""

from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

# Imports de los modelos de billing
from api.models import (
    Plan, PlanFeature, Subscription, PaymentMethod, 
    Invoice, InvoiceItem, Payment, Coupon, Discount, UsageRecord
)


# =============================================================================
# EXTENSIÓN DEL MODELO USER
# =============================================================================
"""
OPCIÓN 1: Agregar estos métodos directamente al modelo User existente
        (copiar y pegar en la clase User de models.py)

OPCIÓN 2: Crear un mixin y heredar de él
        class User(UserBillingMixin, models.Model):
            ...
"""





# =============================================================================
# SIGNAL: Crear suscripción Free al registrar usuario
# =============================================================================
@receiver(post_save, sender='your_app.User')  # Cambiar 'your_app' por tu app
def create_free_subscription_on_user_creation(sender, instance, created, **kwargs):
    """
    CRÍTICO PARA FREEMIUM:
    Cuando se crea un nuevo usuario, automáticamente se le asigna
    una suscripción al plan gratuito.
    
    Esto garantiza que user.active_subscription NUNCA sea None.
    """
    if created:
        # Obtener o crear el plan Free
        free_plan, _ = Plan.objects.get_or_create(
            slug='free',
            defaults={
                'name': 'Gratuito',
                'plan_type': 'free',
                'price': Decimal('0.00'),
                'billing_interval': 'monthly',
                'trial_days': 0,
                'is_active': True,
            }
        )
        
        # Crear suscripción
        now = timezone.now()
        Subscription.objects.create(
            user=instance,
            plan=free_plan,
            status='active',
            started_at=now,
            current_period_start=now,
            # Plan Free: periodo "infinito" (renovación en 100 años)
            current_period_end=now + timedelta(days=36500),
        )


# =============================================================================
# SERVICE: Manejo de Suscripciones
# =============================================================================
class SubscriptionService:
    """
    Servicio para manejar operaciones de suscripción.
    
    PRINCIPIO DE DISEÑO:
    Toda la lógica de negocio de suscripciones está centralizada aquí,
    no dispersa en views o signals.
    """
    
    @staticmethod
    @transaction.atomic
    def upgrade_to_plan(user, new_plan, payment_method=None, coupon_code=None):
        """
        Actualiza al usuario a un nuevo plan.
        
        FLUJO:
        1. Cancela la suscripción actual (si existe)
        2. Crea nueva suscripción
        3. Aplica cupón (si hay)
        4. Genera factura
        5. Intenta cobrar (si el plan no es gratis)
        
        Retorna: (subscription, invoice, error_message)
        """
        now = timezone.now()
        
        # 1. Obtener y cancelar suscripción actual
        current_sub = user.subscriptions.filter(
            status__in=['trialing', 'active', 'past_due']
        ).first()
        
        if current_sub:
            current_sub.status = 'canceled'
            current_sub.canceled_at = now
            current_sub.cancel_reason = 'upgraded'
            current_sub.save()
        
        # 2. Calcular fechas del nuevo periodo
        trial_end = None
        if new_plan.trial_days > 0:
            trial_end = now + timedelta(days=new_plan.trial_days)
            status = 'trialing'
            period_end = trial_end
        else:
            status = 'active'
            period_end = now + timedelta(days=new_plan.interval_days)
        
        # 3. Crear nueva suscripción
        new_subscription = Subscription.objects.create(
            user=user,
            plan=new_plan,
            status=status,
            started_at=now,
            current_period_start=now,
            current_period_end=period_end,
            trial_start=now if trial_end else None,
            trial_end=trial_end,
            default_payment_method=payment_method,
        )
        
        # 4. Aplicar cupón si existe
        discount_amount = Decimal('0.00')
        if coupon_code:
            try:
                coupon = Coupon.objects.get(code=coupon_code.upper())
                if coupon.is_valid:
                    # Crear instancia de descuento
                    end_date = None
                    remaining_months = None
                    
                    if coupon.duration == 'repeating':
                        remaining_months = coupon.duration_in_months
                        if remaining_months:
                            end_date = now + timedelta(days=30 * remaining_months)
                    elif coupon.duration == 'once':
                        end_date = period_end
                    
                    Discount.objects.create(
                        coupon=coupon,
                        subscription=new_subscription,
                        start_date=now,
                        end_date=end_date,
                        remaining_months=remaining_months,
                    )
                    
                    # Incrementar contador de uso
                    coupon.times_redeemed += 1
                    coupon.save()
                    
                    # Calcular descuento
                    if coupon.discount_type == 'percentage':
                        discount_amount = new_plan.price * (coupon.amount / 100)
                    else:
                        discount_amount = min(coupon.amount, new_plan.price)
            except Coupon.DoesNotExist:
                pass  # Cupón inválido, continuar sin descuento
        
        # 5. Generar factura (si no está en trial y no es gratis)
        invoice = None
        if status == 'active' and new_plan.price > 0:
            invoice = SubscriptionService._create_invoice(
                user=user,
                subscription=new_subscription,
                plan=new_plan,
                discount=discount_amount,
            )
            
            # 6. Intentar cobrar si hay método de pago
            if payment_method:
                # Aquí iría la integración con la pasarela
                # Por ahora solo marcamos como pendiente
                pass
        
        return new_subscription, invoice, None
    
    @staticmethod
    def _create_invoice(user, subscription, plan, discount=Decimal('0.00')):
        """Crea una factura para la suscripción."""
        now = timezone.now()
        
        # Generar número de factura
        year = now.year
        count = Invoice.objects.filter(
            invoice_number__startswith=f'INV-{year}'
        ).count() + 1
        invoice_number = f'INV-{year}-{count:05d}'
        
        # Calcular montos
        subtotal = plan.price
        tax = subtotal * Decimal('0.16')  # 16% IVA México
        total = subtotal + tax - discount
        
        invoice = Invoice.objects.create(
            invoice_number=invoice_number,
            user=user,
            subscription=subscription,
            status='open',
            currency=plan.currency,
            subtotal=subtotal,
            tax=tax,
            discount=discount,
            total=total,
            amount_due=total,
            invoice_date=now,
            due_date=now + timedelta(days=7),
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            billing_name=f"{user.first_name} {user.last_name}",
            billing_email=user.email,
        )
        
        # Crear item de la factura
        InvoiceItem.objects.create(
            invoice=invoice,
            item_type='subscription',
            description=f"Suscripción {plan.name}",
            quantity=1,
            unit_price=plan.price,
            amount=plan.price,
            plan=plan,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
        )
        
        if discount > 0:
            InvoiceItem.objects.create(
                invoice=invoice,
                item_type='discount',
                description="Descuento aplicado",
                quantity=1,
                unit_price=-discount,
                amount=-discount,
            )
        
        return invoice
    
    @staticmethod
    @transaction.atomic
    def cancel_subscription(subscription, reason='user_request', immediate=False):
        """
        Cancela una suscripción.
        
        Args:
            subscription: La suscripción a cancelar
            reason: Razón de cancelación
            immediate: Si True, cancela inmediatamente.
                      Si False, cancela al final del periodo (comportamiento estándar).
        """
        now = timezone.now()
        
        if immediate:
            subscription.status = 'canceled'
            subscription.canceled_at = now
        else:
            subscription.cancel_at_period_end = True
        
        subscription.cancel_reason = reason
        subscription.save()
        
        return subscription
    
    @staticmethod
    def handle_payment_failed(subscription, invoice):
        """
        Maneja un pago fallido.
        
        FLUJO DE GRACIA:
        1. Primer fallo → Poner en 'past_due', establecer grace period (7 días)
        2. Durante grace period → Reintentar cobro
        3. Si grace period termina → Cancelar y hacer downgrade a Free
        """
        now = timezone.now()
        
        # Configurar periodo de gracia (7 días)
        grace_days = 7
        
        subscription.status = 'past_due'
        subscription.grace_period_end = now + timedelta(days=grace_days)
        subscription.save()
        
        # Aquí podrías:
        # 1. Enviar email de notificación
        # 2. Enviar push notification
        # 3. Programar reintento de cobro
        
        return subscription
    
    @staticmethod
    def handle_grace_period_expired(subscription):
        """
        Cuando el periodo de gracia expira sin pago exitoso.
        Hace downgrade a plan Free.
        """
        # Cancelar suscripción actual
        subscription.status = 'canceled'
        subscription.canceled_at = timezone.now()
        subscription.cancel_reason = 'payment_failed'
        subscription.save()
        
        # Crear nueva suscripción Free
        user = subscription.user
        free_plan = Plan.objects.get(slug='free')
        
        now = timezone.now()
        Subscription.objects.create(
            user=user,
            plan=free_plan,
            status='active',
            started_at=now,
            current_period_start=now,
            current_period_end=now + timedelta(days=36500),
        )
        
        # Notificar al usuario del downgrade
        # send_downgrade_notification(user)


# =============================================================================
# QUERIES ÚTILES
# =============================================================================
"""
EJEMPLOS DE CONSULTAS COMUNES:

# Usuarios premium activos
User.objects.filter(
    subscriptions__status='active',
    subscriptions__plan__plan_type='premium'
).distinct()

# Suscripciones que expiran hoy (para renovación)
Subscription.objects.filter(
    status='active',
    current_period_end__date=timezone.now().date()
)

# Suscripciones en periodo de gracia expirado
Subscription.objects.filter(
    status='past_due',
    grace_period_end__lt=timezone.now()
)

# Ingresos del mes
from django.db.models import Sum
Payment.objects.filter(
    status='succeeded',
    created_at__month=timezone.now().month,
    created_at__year=timezone.now().year
).aggregate(total=Sum('amount'))

# Usuarios en trial que terminan esta semana
Subscription.objects.filter(
    status='trialing',
    trial_end__lte=timezone.now() + timedelta(days=7),
    trial_end__gte=timezone.now()
)
"""


# =============================================================================
# CONFIGURACIÓN INICIAL DE PLANES (Ejecutar una vez)
# =============================================================================
def setup_initial_plans():
    """
    Crea los planes iniciales del sistema.
    Ejecutar en una migración o management command.
    
    python manage.py shell
    >>> from your_app.billing_helpers import setup_initial_plans
    >>> setup_initial_plans()
    """
    
    # Plan Free
    free_plan, _ = Plan.objects.get_or_create(
        slug='free',
        defaults={
            'name': 'Gratuito',
            'description': 'Perfecto para empezar',
            'plan_type': 'free',
            'price': Decimal('0.00'),
            'currency': 'MXN',
            'billing_interval': 'monthly',
            'trial_days': 0,
            'is_active': True,
            'is_public': True,
            'display_order': 1,
        }
    )
    
    # Features del plan Free
    free_features = [
        ('max_groups', 'Grupos máximos', '2', 'Crea hasta 2 grupos'),
        ('max_blitz_per_day', 'Blitz diarios', '3', 'Hasta 3 sesiones Blitz por día'),
        ('ads_enabled', 'Publicidad', 'true', 'Con anuncios'),
        ('priority_support', 'Soporte prioritario', 'false', ''),
    ]
    
    for key, name, value, desc in free_features:
        PlanFeature.objects.get_or_create(
            plan=free_plan,
            feature_key=key,
            defaults={'feature_name': name, 'value': value, 'description': desc}
        )
    
    # Plan Premium Mensual
    premium_monthly, _ = Plan.objects.get_or_create(
        slug='premium-monthly',
        defaults={
            'name': 'Premium Mensual',
            'description': 'Para usuarios activos',
            'plan_type': 'premium',
            'price': Decimal('99.00'),
            'currency': 'MXN',
            'billing_interval': 'monthly',
            'trial_days': 7,
            'is_active': True,
            'is_public': True,
            'display_order': 2,
        }
    )
    
    # Plan Premium Anual (con descuento)
    premium_yearly, _ = Plan.objects.get_or_create(
        slug='premium-yearly',
        defaults={
            'name': 'Premium Anual',
            'description': '2 meses gratis',
            'plan_type': 'premium',
            'price': Decimal('999.00'),  # ~83/mes vs 99/mes
            'currency': 'MXN',
            'billing_interval': 'yearly',
            'trial_days': 7,
            'is_active': True,
            'is_public': True,
            'display_order': 3,
        }
    )
    
    # Features del plan Premium
    premium_features = [
        ('max_groups', 'Grupos máximos', 'unlimited', 'Grupos ilimitados'),
        ('max_blitz_per_day', 'Blitz diarios', 'unlimited', 'Blitz ilimitados'),
        ('ads_enabled', 'Publicidad', 'false', 'Sin anuncios'),
        ('priority_support', 'Soporte prioritario', 'true', 'Respuesta en 24h'),
        ('see_who_liked', 'Ver quién dio Like', 'true', 'Descubre qué grupos les gustaste'),
        ('blitz_boost', 'Boost de Blitz', 'true', 'Mayor visibilidad en búsquedas'),
    ]
    
    for plan in [premium_monthly, premium_yearly]:
        for key, name, value, desc in premium_features:
            PlanFeature.objects.get_or_create(
                plan=plan,
                feature_key=key,
                defaults={'feature_name': name, 'value': value, 'description': desc}
            )
    
    print(" Planes iniciales creados exitosamente")
    print(f"   - {free_plan.name}")
    print(f"   - {premium_monthly.name} ({premium_monthly.price} {premium_monthly.currency}/mes)")
    print(f"   - {premium_yearly.name} ({premium_yearly.price} {premium_yearly.currency}/año)")
