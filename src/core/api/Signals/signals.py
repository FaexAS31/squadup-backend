"""
Django signals para SquadUp.

Usados para mantener consistencia de datos, validaciones transversales,
y envío de notificaciones push.
"""

import logging
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from api.models import GroupMembership, GroupInvitation, Group, MeetupPlan, SoloMatch

logger = logging.getLogger('api')


# =============================================================================
# FCM PUSH NOTIFICATION SIGNALS
# =============================================================================

def _safe_send_notification(func, *args, **kwargs):
    """Wrapper to safely send notifications without breaking the save."""
    try:
        func(*args, **kwargs)
    except Exception as e:
        logger.error(f"FCM notification error: {e}")


def _is_match_muted(user_id, match_id):
    """Check if a user has muted a specific match."""
    from api.models import MatchMute
    return MatchMute.objects.filter(user_id=user_id, match_id=match_id).exists()


@receiver(post_save, sender='api.Match')
def notify_match_created(sender, instance, created, **kwargs):
    """Send push notification when a new match is created."""
    if not created:
        return

    try:
        from utils.fcm_service import notify_new_match

        match = instance

        # Get both groups involved in the match (blitz_1 and blitz_2 are Blitz objects)
        blitz1 = match.blitz_1
        blitz2 = match.blitz_2

        if not blitz1 or not blitz2:
            return

        group1 = blitz1.group
        group2 = blitz2.group

        if not group1 or not group2:
            return

        # Notify all members of group1 about matching with group2
        for membership in group1.groupmembership_set.all():
            if membership.user_id and not _is_match_muted(membership.user_id, match.id):
                _safe_send_notification(
                    notify_new_match,
                    match_id=match.id,
                    user_id=membership.user_id,
                    other_group_name=group2.name,
                )

        # Notify all members of group2 about matching with group1
        for membership in group2.groupmembership_set.all():
            if membership.user_id and not _is_match_muted(membership.user_id, match.id):
                _safe_send_notification(
                    notify_new_match,
                    match_id=match.id,
                    user_id=membership.user_id,
                    other_group_name=group1.name,
                )

        logger.info(f"Match notification sent for match {match.id}")

    except Exception as e:
        logger.error(f"Error sending match notification: {e}")


@receiver(post_save, sender='api.Message')
def notify_new_message(sender, instance, created, **kwargs):
    """Send push notification when a new message is sent."""
    if not created:
        return

    try:
        from utils.fcm_service import notify_new_message as send_message_notification

        message = instance
        chat = message.chat

        if not chat or not message.sender:
            return

        # Get sender info
        sender_user = message.sender
        sender_name = sender_user.first_name or sender_user.email.split('@')[0]

        # Get all chat participants except the sender
        if chat.match:
            match = chat.match

            groups_to_notify = []
            if match.blitz_1 and match.blitz_1.group:
                groups_to_notify.append(match.blitz_1.group)
            if match.blitz_2 and match.blitz_2.group:
                groups_to_notify.append(match.blitz_2.group)

            notified_users = set()
            for group in groups_to_notify:
                if not group:
                    continue
                for membership in group.groupmembership_set.all():
                    user_id = membership.user_id
                    if (user_id and user_id != sender_user.id and
                            user_id not in notified_users and
                            not _is_match_muted(user_id, match.id)):
                        notified_users.add(user_id)
                        _safe_send_notification(
                            send_message_notification,
                            chat_id=chat.id,
                            user_id=user_id,
                            sender_name=sender_name,
                            message_preview=message.text,
                        )

        logger.info(f"Message notification sent for chat {chat.id}")

    except Exception as e:
        logger.error(f"Error sending message notification: {e}")


@receiver(post_save, sender='api.Friendship')
def notify_friend_request(sender, instance, created, **kwargs):
    """Send push notification when a friend request is sent."""
    # Friendship uses lowercase status ('pending', 'accepted', etc.)
    if not created or instance.status != 'pending':
        return

    try:
        from utils.fcm_service import notify_friend_request as send_friend_notification

        friendship = instance
        # Friendship uses user_from and user_to
        requester = friendship.user_from
        recipient = friendship.user_to

        if not requester or not recipient:
            return

        requester_name = requester.first_name or requester.email.split('@')[0]

        _safe_send_notification(
            send_friend_notification,
            user_id=recipient.id,
            from_user_name=requester_name,
        )

        logger.info(f"Friend request notification sent from {requester.id} to {recipient.id}")

    except Exception as e:
        logger.error(f"Error sending friend request notification: {e}")


@receiver(post_save, sender='api.BlitzInteraction')
def notify_group_liked(sender, instance, created, **kwargs):
    """Send push notification when a group likes another group."""
    # BlitzInteraction uses lowercase interaction_type ('like', 'skip')
    if not created or instance.interaction_type != 'like':
        return

    try:
        from utils.fcm_service import notify_group_liked as send_like_notification

        interaction = instance
        # BlitzInteraction uses to_blitz and from_blitz
        target_blitz = interaction.to_blitz
        if not target_blitz or not target_blitz.group:
            return

        target_group = target_blitz.group
        liker_blitz = interaction.from_blitz
        if not liker_blitz or not liker_blitz.group:
            return

        liker_group = liker_blitz.group

        for membership in target_group.groupmembership_set.all():
            if membership.user_id:
                _safe_send_notification(
                    send_like_notification,
                    user_id=membership.user_id,
                    liker_group_name=liker_group.name,
                )

        logger.info(f"Group like notification sent for {liker_group.name} -> {target_group.name}")

    except Exception as e:
        logger.error(f"Error sending group like notification: {e}")


    # NOTE: Vote request notifications for democratic mode are sent directly
    # in BlitzInteractionViewSet.create() (lines 150-164), not via signal.
    # A previous signal here was removed because:
    # 1. BlitzInteraction has no user_id field (caused AttributeError)
    # 2. It didn't check requires_consensus (would fire for leader mode too)
    # 3. It duplicated the viewset's notification logic


@receiver(post_save, sender='api.GroupMembership')
def notify_group_member_joined(sender, instance, created, **kwargs):
    """Send push notification when a new member joins a group."""
    if not created:
        return

    try:
        from utils.fcm_service import notify_group_invite

        membership = instance
        new_user = membership.user
        group = membership.group

        if not new_user or not group:
            return

        new_user_name = new_user.first_name or new_user.email.split('@')[0]

        # Notify all existing group members except the new member
        for existing in group.groupmembership_set.exclude(user_id=new_user.id):
            if existing.user_id:
                _safe_send_notification(
                    notify_group_invite,
                    user_id=existing.user_id,
                    group_name=group.name,
                    inviter_name=new_user_name,
                )

        logger.info(f"Group join notification sent for {new_user.id} joining {group.name}")

    except Exception as e:
        logger.error(f"Error sending group join notification: {e}")


@receiver(post_save, sender=MeetupPlan)
def notify_meetup_created(sender, instance, created, **kwargs):
    """Send push notification when a meetup is proposed."""
    if not created:
        return

    try:
        from utils.fcm_service import notify_meetup_proposed

        meetup = instance
        match = meetup.match
        proposer = meetup.proposed_by

        if not match or not proposer:
            return

        proposer_name = proposer.first_name or proposer.email.split('@')[0]
        location = meetup.location_name or meetup.title

        # Get both groups from the match
        groups_to_notify = []
        if match.blitz_1 and match.blitz_1.group:
            groups_to_notify.append(match.blitz_1.group)
        if match.blitz_2 and match.blitz_2.group:
            groups_to_notify.append(match.blitz_2.group)

        notified_users = set()
        for group in groups_to_notify:
            for membership in group.groupmembership_set.all():
                user_id = membership.user_id
                if user_id and user_id != proposer.id and user_id not in notified_users:
                    notified_users.add(user_id)
                    _safe_send_notification(
                        notify_meetup_proposed,
                        user_id=user_id,
                        group_name=proposer_name,
                        location=location,
                    )

        logger.info(f"Meetup proposed notification sent for meetup {meetup.id}")

    except Exception as e:
        logger.error(f"Error sending meetup proposed notification: {e}")


@receiver(pre_save, sender=MeetupPlan)
def notify_meetup_status_changed(sender, instance, **kwargs):
    """Send push notification when a meetup is confirmed."""
    if not instance.pk:
        return  # New object, handled by post_save

    try:
        old = MeetupPlan.objects.get(pk=instance.pk)
    except MeetupPlan.DoesNotExist:
        return

    if old.status == instance.status:
        return  # Status didn't change

    if instance.status != 'confirmed':
        return  # Only notify on confirmation

    try:
        from utils.fcm_service import notify_meetup_confirmed

        meetup = instance
        match = meetup.match

        if not match:
            return

        location = meetup.location_name or meetup.title
        time_str = meetup.scheduled_at.strftime('%b %d at %I:%M %p') if meetup.scheduled_at else ''

        # Get both groups from the match
        groups_to_notify = []
        if match.blitz_1 and match.blitz_1.group:
            groups_to_notify.append(match.blitz_1.group)
        if match.blitz_2 and match.blitz_2.group:
            groups_to_notify.append(match.blitz_2.group)

        notified_users = set()
        for group in groups_to_notify:
            for membership in group.groupmembership_set.all():
                user_id = membership.user_id
                if user_id and user_id not in notified_users:
                    notified_users.add(user_id)
                    _safe_send_notification(
                        notify_meetup_confirmed,
                        user_id=user_id,
                        location=location,
                        time=time_str,
                    )

        logger.info(f"Meetup confirmed notification sent for meetup {meetup.id}")

    except Exception as e:
        logger.error(f"Error sending meetup confirmed notification: {e}")


@receiver(post_save, sender=GroupInvitation)
def notify_group_invitation(sender, instance, created, **kwargs):
    """Send push notification when a user is invited to a group."""
    if not created or instance.status != 'pending':
        return

    try:
        from utils.fcm_service import send_notification_to_user

        invitation = instance
        inviter = invitation.inviter
        group = invitation.group

        if not inviter or not group:
            return

        inviter_name = inviter.first_name or inviter.email.split('@')[0]

        _safe_send_notification(
            send_notification_to_user,
            user_id=invitation.invitee_id,
            title="👥 Invitación a grupo",
            body=f"{inviter_name} te invitó a unirte a {group.name}",
            data={
                'action': 'open_notifications',
                'invitation_id': str(invitation.id),
                'group_id': str(group.id),
                'sender_id': inviter.id,
            },
            notification_type='GROUP_INVITE',
        )

        logger.info(
            f"Group invitation notification sent: "
            f"{inviter.id} invited {invitation.invitee_id} to group {group.id}"
        )

    except Exception as e:
        logger.error(f"Error sending group invitation notification: {e}")


@receiver(post_save, sender=SoloMatch)
def notify_solo_match(sender, instance, created, **kwargs):
    """Send push notifications for Solo Mode match events."""
    try:
        from utils.fcm_service import send_notification_to_user

        solo = instance

        if created and solo.status == 'pending':
            # Notify target user of incoming connection
            requester = solo.user_a
            requester_name = requester.first_name or requester.email.split('@')[0]
            _safe_send_notification(
                send_notification_to_user,
                user_id=solo.user_b_id,
                title="🤝 Nueva conexión",
                body=f"{requester_name} quiere conectar contigo",
                data={
                    'action': 'open_solo_mode',
                    'solo_match_id': str(solo.id),
                    'sender_id': solo.user_a_id,
                },
                notification_type='SOLO_CONNECTION',
            )
            logger.info(f"Solo connection notification: {solo.user_a_id} → {solo.user_b_id}")

        elif solo.status == 'matched':
            # Notify both users of mutual match
            user_a_name = solo.user_a.first_name or solo.user_a.email.split('@')[0]
            user_b_name = solo.user_b.first_name or solo.user_b.email.split('@')[0]

            _safe_send_notification(
                send_notification_to_user,
                user_id=solo.user_a_id,
                title="⚡ ¡Es un Match!",
                body=f"Tú y {user_b_name} quieren conectar. ¡Coordinen su encuentro!",
                data={
                    'action': 'open_coordination',
                    'solo_match_id': str(solo.id),
                    'sender_id': solo.user_b_id,
                },
                notification_type='SOLO_MATCH',
            )
            _safe_send_notification(
                send_notification_to_user,
                user_id=solo.user_b_id,
                title="⚡ ¡Es un Match!",
                body=f"Tú y {user_a_name} quieren conectar. ¡Coordinen su encuentro!",
                data={
                    'action': 'open_coordination',
                    'solo_match_id': str(solo.id),
                    'sender_id': solo.user_a_id,
                },
                notification_type='SOLO_MATCH',
            )
            logger.info(f"Solo match notification: {solo.user_a_id} <-> {solo.user_b_id}")

    except Exception as e:
        logger.error(f"Error sending solo match notification: {e}")


# =============================================================================
# DATA CONSISTENCY SIGNALS
# =============================================================================


@receiver(post_save, sender=GroupMembership)
def sync_group_membership_on_save(sender, instance, created, **kwargs):
    """
    Cuando se crea/actualiza GroupMembership, asegurar que Group.members
    está en sync y validar que el grupo tiene al menos un LEADER.
    """
    group = instance.group
    
    # Validaciones
    if instance.user not in group.members.all():
        logger.warning(
            f"⚠️ Membresía desincronizada: {instance.user} no está en {group}.members"
        )
    
    # Verificar que el grupo siempre tiene un LEADER
    leader_count = group.groupmembership_set.filter(role='admin').count()
    if leader_count == 0:
        logger.error(
            f"🔴 CRÍTICO: Grupo {group.id} sin LEADER. "
            f"Esto puede ocurrir si se elimina el último admin sin asignar uno nuevo."
        )


@receiver(post_delete, sender=GroupMembership)
def validate_group_on_delete(sender, instance, **kwargs):
    """
    Cuando se elimina un miembro, asegurar que el grupo sigue válido.
    
    Si se elimina el último miembro, desactivar grupo.
    Si se elimina el último LEADER, loguear error crítico.
    """
    group = instance.group
    
    # Si se elimina el último miembro, desactivar grupo
    if group.members.count() == 0:
        group.is_active = False
        group.save()
        logger.info(f"Grupo desactivado (sin miembros): {group.id}")
    
    # Verificar si aún hay LEADER
    leader_count = group.groupmembership_set.filter(role='admin').count()
    if leader_count == 0 and group.members.count() > 0:
        logger.error(
            f"🔴 CRÍTICO: Grupo {group.id} sin LEADER pero con {group.members.count()} miembros. "
            f"Requiere intervención inmediata."
        )


@receiver(pre_save, sender=Group)
def validate_group_before_save(sender, instance, **kwargs):
    """
    Validaciones antes de guardar un Group.
    """
    # Si se intenta desactivar sin motivo, loguear
    if instance.pk and not instance.is_active:
        original = Group.objects.get(pk=instance.pk)
        if original.is_active:
            logger.info(f"Grupo {instance.id} marcado como inactivo")
