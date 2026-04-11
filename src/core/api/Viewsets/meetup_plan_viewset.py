import logging
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from drf_spectacular.utils import extend_schema

from api.models import MeetupPlan, MatchActivity, Notification, GroupMembership
from api.Serializers.meetup_plan_serializer import MeetupPlanSerializer

logger = logging.getLogger('api')


def _get_match_member_ids(match):
    """Return set of user IDs from both groups in a match."""
    ids = set()
    for blitz in [match.blitz_1, match.blitz_2]:
        if blitz and blitz.group:
            ids.update(
                GroupMembership.objects.filter(group=blitz.group)
                .values_list('user_id', flat=True)
            )
    return ids


@extend_schema(tags=['MeetupPlans'])
class MeetupPlanViewSet(viewsets.ModelViewSet):
    """
    ViewSet for MeetupPlans.

    Supports filtering by:
    - match: Filter plans by match ID

    Auto-sets proposed_by to the requesting user on creation
    and creates a MatchActivity timeline entry.
    """
    queryset = MeetupPlan.objects.all()
    serializer_class = MeetupPlanSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['match', 'status']

    def get_queryset(self):
        return MeetupPlan.objects.all().select_related(
            'match', 'match__blitz_1', 'match__blitz_2',
            'match__blitz_1__group', 'match__blitz_2__group',
            'proposed_by',
        ).order_by('-scheduled_at')

    def perform_create(self, serializer):
        plan = serializer.save(proposed_by=self.request.user)
        user = self.request.user
        name = user.first_name or user.email

        # Auto-create timeline activity
        MatchActivity.objects.create(
            match=plan.match,
            activity_type='plan_suggested',
            triggered_by=user,
            description=f'{name} propuso: {plan.title}',
        )

        # Notify match members
        member_ids = _get_match_member_ids(plan.match)
        for uid in member_ids:
            if uid != user.id:
                Notification.objects.create(
                    user_id=uid,
                    notification_type='meetup_proposed',
                    title='Nuevo plan de meetup',
                    body=f'{name} propuso: {plan.title}',
                    data={
                        'match_id': plan.match_id,
                        'plan_id': plan.id,
                        'action': 'open_match',
                        'sender_id': user.id,
                    },
                )

        logger.info(f"MeetupPlan created: {plan.id} for match {plan.match_id} by user {user.id}")

    def perform_update(self, serializer):
        plan = serializer.save()
        user = self.request.user

        # Track status changes as activities + notifications
        if 'status' in serializer.validated_data:
            new_status = serializer.validated_data['status']
            activity_map = {
                'accepted': 'plan_accepted',
                'confirmed': 'meetup_confirmed',
                'completed': 'meetup_completed',
            }
            notif_map = {
                'confirmed': ('meetup_confirmed', '¡Meetup confirmado!', f'{plan.title} ha sido confirmado'),
                'cancelled': ('meetup_proposed', 'Plan cancelado', f'{plan.title} fue cancelado'),
            }
            activity_type = activity_map.get(new_status)
            if activity_type:
                MatchActivity.objects.create(
                    match=plan.match,
                    activity_type=activity_type,
                    triggered_by=user,
                    description=f'{plan.title} — {plan.get_status_display()}',
                )
            notif_info = notif_map.get(new_status)
            if notif_info:
                ntype, ntitle, nbody = notif_info
                member_ids = _get_match_member_ids(plan.match)
                for uid in member_ids:
                    if uid != user.id:
                        Notification.objects.create(
                            user_id=uid,
                            notification_type=ntype,
                            title=ntitle,
                            body=nbody,
                            data={
                                'match_id': plan.match_id,
                                'plan_id': plan.id,
                                'action': 'open_match',
                                'sender_id': user.id,
                            },
                        )
