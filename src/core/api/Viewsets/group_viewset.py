import logging
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle
from api.models import Group, GroupMembership, GroupInvitation, Blitz, Friendship, User


class JoinGroupThrottle(UserRateThrottle):
    rate = '10/min'
from api.Serializers.group_serializer import GroupSerializer
from api.Serializers.blitz_serializer import BlitzSerializer
from drf_spectacular.utils import extend_schema, OpenApiParameter

logger = logging.getLogger('api')

@extend_schema(tags=['Groups'])
class GroupViewSet(viewsets.ModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

    def get_queryset(self):
        """Filter groups to only return groups where the current user is a member."""
        qs = super().get_queryset()
        user = self.request.user
        if user and hasattr(user, 'id') and user.id:
            return qs.filter(members=user, is_active=True).distinct()
        return qs.none()

    def list(self, request, *args, **kwargs):
        logger.debug(f"Listing groups for user: {request.user}")
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """Check freemium group limit before creating."""
        user = request.user
        limit = user.get_feature_limit('max_groups')
        if limit != -1:
            current = user.groups.filter(is_active=True).count()
            if current >= limit:
                return Response(
                    {
                        'error': 'limit_reached',
                        'feature': 'max_groups',
                        'limit': limit,
                        'current': current,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """Auto-set creator and add them as admin member."""
        group = serializer.save(creator=self.request.user)
        GroupMembership.objects.create(
            group=group,
            user=self.request.user,
            role='admin',
        )
        logger.info(
            f"Group created: ID {group.id} - Name: {group.name} "
            f"- Creator: {self.request.user.id} (auto-added as admin)"
        )

    def destroy(self, request, *args, **kwargs):
        group = self.get_object()

        is_admin = GroupMembership.objects.filter(
            group=group, user=request.user, role='admin'
        ).exists()
        is_creator = request.user == group.creator

        if not (is_admin or is_creator):
            return Response(
                {'error': 'Solo el admin puede eliminar el grupo'},
                status=status.HTTP_403_FORBIDDEN
            )

        logger.warning(
            f"Group DELETED: ID {group.id} - Name: {group.name} "
            f"- Members: {group.member_count} - By user: {request.user.id}"
        )
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        tags=['Groups'],
        summary='Invite friends to group',
        description='Invite accepted friends to a group by user IDs. Creates pending invitations.',
    )
    @action(detail=True, methods=['post'], url_path='invite-members', permission_classes=[IsAuthenticated])
    def invite_members(self, request, pk=None):
        """
        POST /api/groups/{id}/invite-members/
        Body: {"user_ids": [1, 2, 3]}
        Creates GroupInvitation (pending) for each friend. Users must accept to join.
        """
        from django.db.models import Q

        group = self.get_object()

        is_admin = GroupMembership.objects.filter(
            group=group, user=request.user, role='admin'
        ).exists()
        if not is_admin:
            return Response(
                {'error': 'Solo los admins pueden invitar miembros'},
                status=status.HTTP_403_FORBIDDEN
            )

        user_ids = request.data.get('user_ids', [])
        if not user_ids:
            return Response(
                {'error': 'user_ids es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        results = []
        for uid in user_ids:
            # Check blocked (either direction)
            is_blocked = Friendship.objects.filter(
                Q(user_from=request.user, user_to_id=uid, status='blocked') |
                Q(user_from_id=uid, user_to=request.user, status='blocked')
            ).exists()
            if is_blocked:
                results.append({'user_id': uid, 'status': 'not_friend'})
                continue

            is_friend = Friendship.objects.filter(
                Q(user_from=request.user, user_to_id=uid) |
                Q(user_from_id=uid, user_to=request.user),
                status='accepted'
            ).exists()

            if not is_friend:
                results.append({'user_id': uid, 'status': 'not_friend'})
                continue

            if GroupMembership.objects.filter(group=group, user_id=uid).exists():
                results.append({'user_id': uid, 'status': 'already_member'})
                continue

            # Check for existing pending invitation
            if GroupInvitation.objects.filter(
                group=group, invitee_id=uid, status=GroupInvitation.Status.PENDING
            ).exists():
                results.append({'user_id': uid, 'status': 'already_invited'})
                continue

            invitation = GroupInvitation.objects.create(
                group=group,
                inviter=request.user,
                invitee_id=uid,
                status=GroupInvitation.Status.PENDING,
            )
            results.append({
                'user_id': uid,
                'status': 'invited',
                'invitation_id': invitation.id,
            })

        logger.info(
            f"Invite-members for group {group.id} by user {request.user.id}: {results}"
        )
        return Response({'results': results}, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Groups'],
        summary='Get group invite code',
        description='Returns the invite code for a group. Only group members can see this.',
    )
    @action(detail=True, methods=['get'], url_path='invite-code', permission_classes=[IsAuthenticated])
    def invite_code(self, request, pk=None):
        """Get the invite code for a group."""
        group = self.get_object()

        # Check if user is a member
        is_member = GroupMembership.objects.filter(
            group=group, user=request.user
        ).exists()

        if not is_member:
            return Response(
                {'error': 'You must be a member of this group to get the invite code'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Generate code if doesn't exist
        if not group.invite_code:
            group.save()  # This triggers auto-generation

        return Response({
            'invite_code': group.invite_code,
            'group_id': group.id,
            'group_name': group.name,
        })

    @extend_schema(
        tags=['Groups'],
        summary='Regenerate invite code',
        description='Regenerates the invite code for a group. Only admins can do this.',
    )
    @action(detail=True, methods=['post'], url_path='regenerate-invite', permission_classes=[IsAuthenticated])
    def regenerate_invite(self, request, pk=None):
        """Regenerate the invite code (admin only)."""
        group = self.get_object()

        # Check if user is admin
        is_admin = GroupMembership.objects.filter(
            group=group, user=request.user, role='admin'
        ).exists()

        if not is_admin:
            return Response(
                {'error': 'Only group admins can regenerate invite codes'},
                status=status.HTTP_403_FORBIDDEN
            )

        new_code = group.regenerate_invite_code()
        logger.info(f"Invite code regenerated for group {group.id} by user {request.user.id}")

        return Response({
            'invite_code': new_code,
            'group_id': group.id,
            'message': 'Invite code regenerated successfully',
        })

    @extend_schema(
        tags=['Groups'],
        summary='Join group via invite code',
        description='Join a group using an invite code. Creates a membership for the current user.',
        parameters=[
            OpenApiParameter(
                name='code',
                type=str,
                description='The invite code',
                required=True,
            ),
        ],
    )
    @action(detail=False, methods=['post'], url_path='join', permission_classes=[IsAuthenticated], throttle_classes=[JoinGroupThrottle])
    def join_by_invite(self, request):
        """Join a group using an invite code."""
        code = request.data.get('code', '').strip().upper()

        if not code:
            return Response(
                {'error': 'Invite code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Find group by invite code
        try:
            group = Group.objects.get(invite_code=code, is_active=True)
        except Group.DoesNotExist:
            return Response(
                {'error': 'Invalid invite code'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Atomically check + create membership to prevent race condition
        membership, created = GroupMembership.objects.get_or_create(
            group=group,
            user=request.user,
            defaults={'role': 'member'}
        )

        if not created:
            return Response({
                'error': 'Ya eres miembro de este grupo',
                'group_id': group.id,
            }, status=status.HTTP_409_CONFLICT)

        logger.info(f"User {request.user.id} joined group {group.id} via invite code")

        # Return group info
        serializer = self.get_serializer(group)
        return Response({
            'message': f'Successfully joined {group.name}!',
            'group': serializer.data,
            'membership_id': membership.id,
        }, status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=['Groups'],
        summary='Preview group by invite code',
        description='Get basic group info from an invite code without joining.',
        parameters=[
            OpenApiParameter(
                name='code',
                type=str,
                description='The invite code',
                required=True,
            ),
        ],
    )
    @action(detail=False, methods=['get'], url_path='preview', permission_classes=[IsAuthenticated])
    def preview_by_invite(self, request):
        """Preview a group using an invite code (without joining)."""
        code = request.query_params.get('code', '').strip().upper()

        if not code:
            return Response(
                {'error': 'Invite code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Find group by invite code
        try:
            group = Group.objects.get(invite_code=code, is_active=True)
        except Group.DoesNotExist:
            return Response(
                {'error': 'Invalid invite code'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Check if already a member
        is_member = GroupMembership.objects.filter(
            group=group, user=request.user
        ).exists()

        return Response({
            'group_id': group.id,
            'group_name': group.name,
            'member_count': group.member_count,
            'description': group.description,
            'is_member': is_member,
        })

    @extend_schema(
        tags=['Groups'],
        summary='Quick duo: create group + blitz atomically',
        description='Creates a 2-person group and starts a Blitz session. Requires mutual friendship.',
    )
    @action(detail=False, methods=['post'], url_path='quick_duo', permission_classes=[IsAuthenticated])
    def quick_duo(self, request):
        """
        POST /api/groups/quick_duo/ — Solo Mode: atomically create group + blitz.

        Body: {"other_user_id": 456, "activity_type": "coffee", "duration_minutes": 60}
        """
        user = request.user
        other_user_id = request.data.get('other_user_id')
        activity_type = request.data.get('activity_type', '')
        duration_minutes = request.data.get('duration_minutes', 60)

        if not other_user_id:
            return Response(
                {'error': 'other_user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            other_user = User.objects.get(id=other_user_id, is_active=True)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        # Verify mutual friendship
        mutual = Friendship.objects.filter(
            user_from=user, user_to=other_user, status='accepted'
        ).exists() and Friendship.objects.filter(
            user_from=other_user, user_to=user, status='accepted'
        ).exists()

        if not mutual:
            return Response(
                {'error': 'Mutual friendship required to start a duo Blitz'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            with transaction.atomic():
                # Create 2-person group
                group = Group.objects.create(
                    name=f"You & {other_user.first_name}",
                    creator=user,
                    description=f"Solo Mode duo for {activity_type or 'Blitz'}",
                    metadata={'source': 'solo'},
                )

                # Add both members
                GroupMembership.objects.create(
                    group=group, user=user, role='admin'
                )
                GroupMembership.objects.create(
                    group=group, user=other_user, role='member'
                )

                # Create Blitz session
                now = timezone.now()
                blitz = Blitz.objects.create(
                    group=group,
                    leader=user,
                    status='active',
                    started_at=now,
                    expires_at=now + timedelta(minutes=int(duration_minutes)),
                    activity_type=activity_type,
                )

            logger.info(
                f"Quick duo created: group {group.id}, blitz {blitz.id} "
                f"by user {user.id} with {other_user.id}"
            )

            group_serializer = GroupSerializer(group, context={'request': request})
            blitz_serializer = BlitzSerializer(blitz, context={'request': request})

            return Response({
                'group': group_serializer.data,
                'blitz': blitz_serializer.data,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Quick duo creation failed: {str(e)}")
            return Response(
                {'error': 'Failed to create duo session'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
