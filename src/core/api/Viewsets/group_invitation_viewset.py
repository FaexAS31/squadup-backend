import logging
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.models import GroupInvitation, GroupMembership
from api.Serializers.group_invitation_serializer import GroupInvitationSerializer
from drf_spectacular.utils import extend_schema

logger = logging.getLogger('api')


@extend_schema(tags=['GroupInvitations'])
class GroupInvitationViewSet(viewsets.ModelViewSet):
    serializer_class = GroupInvitationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Return invitations visible to the current user.

        - Default: invitations where the user is the invitee (received).
        - With ?group=<id>: all invitations for that group, if the user
          is a member (used by InviteFriendsModal to show pending state).
        """
        from django.db.models import Q

        user = self.request.user
        group_id = self.request.query_params.get('group')

        if group_id:
            # Show all invitations for this group if the user is a member
            is_member = GroupMembership.objects.filter(
                group_id=group_id, user=user
            ).exists()
            if is_member:
                qs = GroupInvitation.objects.filter(group_id=group_id)
            else:
                qs = GroupInvitation.objects.none()
        else:
            # Default: invitations received by the current user
            qs = GroupInvitation.objects.filter(invitee=user)

        qs = qs.select_related('group', 'inviter', 'invitee').order_by('-created_at')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @extend_schema(summary='Accept a group invitation')
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def accept(self, request, pk=None):
        invitation = self.get_object()

        if invitation.invitee_id != request.user.id:
            return Response(
                {'detail': 'No puedes aceptar esta invitación'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if invitation.status != GroupInvitation.Status.PENDING:
            return Response(
                {'detail': f'Invitación ya fue {invitation.get_status_display().lower()}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            GroupMembership.objects.create(
                group=invitation.group,
                user=request.user,
                role='member',
            )
        except IntegrityError:
            # Already a member (race condition)
            pass

        invitation.status = GroupInvitation.Status.ACCEPTED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=['status', 'responded_at'])

        logger.info(
            f"Invitation {invitation.id} accepted: "
            f"user {request.user.id} joined group {invitation.group_id}"
        )
        return Response({'detail': 'Invitación aceptada'})

    @extend_schema(summary='Decline a group invitation')
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def decline(self, request, pk=None):
        invitation = self.get_object()

        if invitation.invitee_id != request.user.id:
            return Response(
                {'detail': 'No puedes rechazar esta invitación'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if invitation.status != GroupInvitation.Status.PENDING:
            return Response(
                {'detail': f'Invitación ya fue {invitation.get_status_display().lower()}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invitation.status = GroupInvitation.Status.DECLINED
        invitation.responded_at = timezone.now()
        invitation.save(update_fields=['status', 'responded_at'])

        logger.info(f"Invitation {invitation.id} declined by user {request.user.id}")
        return Response({'detail': 'Invitación rechazada'})
