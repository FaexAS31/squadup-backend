"""
Firebase Cloud Messaging (FCM) Service for push notifications.

This module handles sending push notifications to mobile devices
using Firebase Admin SDK.
"""
import logging
from typing import Optional, List, Dict, Any
from django.conf import settings

import firebase_admin
from firebase_admin import messaging

logger = logging.getLogger(__name__)


def _get_firebase_app():
    """Get or initialize Firebase app."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        # App not initialized - this shouldn't happen if auth is configured
        logger.warning("Firebase app not initialized - FCM will not work")
        return None


def send_push_notification(
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    image_url: Optional[str] = None,
    badge: Optional[int] = None,
) -> bool:
    """
    Send a push notification to a single device.

    Args:
        token: FCM device token
        title: Notification title
        body: Notification body text
        data: Optional data payload (must be string values)
        image_url: Optional image URL for rich notifications
        badge: Optional badge count for iOS

    Returns:
        True if sent successfully, False otherwise
    """
    app = _get_firebase_app()
    if not app:
        logger.error("Firebase app not available - cannot send notification")
        return False

    try:
        # Build notification
        notification = messaging.Notification(
            title=title,
            body=body,
            image=image_url,
        )

        # iOS-specific config
        apns = messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    badge=badge,
                    sound='default',
                    content_available=True,
                ),
            ),
        )

        # Android-specific config
        android = messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                sound='default',
                default_vibrate_timings=True,
                default_light_settings=True,
            ),
        )

        # Build message
        message = messaging.Message(
            notification=notification,
            data=data or {},
            token=token,
            apns=apns,
            android=android,
        )

        # Send message
        response = messaging.send(message)
        logger.info(f"FCM notification sent successfully: {response}")
        return True

    except messaging.UnregisteredError:
        # Token is no longer valid - mark it as inactive
        logger.warning(f"FCM token unregistered: {token[:20]}...")
        _deactivate_token(token)
        return False

    except messaging.SenderIdMismatchError:
        logger.error(f"FCM sender ID mismatch for token: {token[:20]}...")
        _deactivate_token(token)
        return False

    except Exception as e:
        logger.error(f"FCM send error: {e}")
        return False


def send_push_notification_batch(
    tokens: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a push notification to multiple devices.

    Args:
        tokens: List of FCM device tokens
        title: Notification title
        body: Notification body text
        data: Optional data payload (must be string values)
        image_url: Optional image URL for rich notifications

    Returns:
        Dict with 'success_count', 'failure_count', and 'failed_tokens'
    """
    app = _get_firebase_app()
    if not app:
        logger.error("Firebase app not available - cannot send notifications")
        return {'success_count': 0, 'failure_count': len(tokens), 'failed_tokens': tokens}

    if not tokens:
        return {'success_count': 0, 'failure_count': 0, 'failed_tokens': []}

    try:
        # Build notification
        notification = messaging.Notification(
            title=title,
            body=body,
            image=image_url,
        )

        # Build multicast message
        message = messaging.MulticastMessage(
            notification=notification,
            data=data or {},
            tokens=tokens,
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound='default', content_available=True),
                ),
            ),
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(sound='default'),
            ),
        )

        # Send batch
        response = messaging.send_each_for_multicast(message)

        # Process results
        failed_tokens = []
        for idx, send_response in enumerate(response.responses):
            if not send_response.success:
                failed_tokens.append(tokens[idx])
                # Check if token should be deactivated
                if send_response.exception:
                    exc = send_response.exception
                    if isinstance(exc, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
                        _deactivate_token(tokens[idx])

        logger.info(
            f"FCM batch sent: {response.success_count} success, "
            f"{response.failure_count} failed"
        )

        return {
            'success_count': response.success_count,
            'failure_count': response.failure_count,
            'failed_tokens': failed_tokens,
        }

    except Exception as e:
        logger.error(f"FCM batch send error: {e}")
        return {'success_count': 0, 'failure_count': len(tokens), 'failed_tokens': tokens}


def send_notification_to_user(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    notification_type: Optional[str] = None,
    save_to_db: bool = True,
) -> Dict[str, Any]:
    """
    Send a push notification to all of a user's active devices.

    Also creates a Notification record in the database.

    Args:
        user_id: ID of the user to notify
        title: Notification title
        body: Notification body text
        data: Optional data payload
        notification_type: Type of notification (for database record)
        save_to_db: Whether to save notification to database

    Returns:
        Dict with 'sent_count', 'failed_count', 'notification_id'
    """
    from api.models import DeviceToken, Notification, User

    # Get user's active tokens
    tokens = list(
        DeviceToken.objects.filter(user_id=user_id, is_active=True)
        .values_list('token', flat=True)
    )

    result = {
        'sent_count': 0,
        'failed_count': 0,
        'notification_id': None,
    }

    # Save notification to database
    notification_record = None
    if save_to_db:
        try:
            notification_record = Notification.objects.create(
                user_id=user_id,
                notification_type=notification_type or 'system',
                title=title,
                body=body,
                data=data or {},
            )
            result['notification_id'] = notification_record.id
        except Exception as e:
            logger.error(f"Failed to save notification to DB: {e}")

    # Send push notifications
    if tokens:
        # Add notification_id to data payload
        push_data = {**(data or {})}
        if notification_record:
            push_data['notification_id'] = str(notification_record.id)
        if notification_type:
            push_data['type'] = notification_type

        batch_result = send_push_notification_batch(
            tokens=tokens,
            title=title,
            body=body,
            data=push_data,
        )
        result['sent_count'] = batch_result['success_count']
        result['failed_count'] = batch_result['failure_count']

        # Update notification record with FCM status
        if notification_record and batch_result['success_count'] > 0:
            from django.utils import timezone
            notification_record.fcm_sent = True
            notification_record.fcm_sent_at = timezone.now()
            notification_record.save(update_fields=['fcm_sent', 'fcm_sent_at'])

    return result


def _deactivate_token(token: str):
    """Mark a token as inactive in the database."""
    try:
        from api.models import DeviceToken
        DeviceToken.objects.filter(token=token).update(is_active=False)
        logger.info(f"Deactivated invalid FCM token: {token[:20]}...")
    except Exception as e:
        logger.error(f"Failed to deactivate token: {e}")


# =============================================================================
# Convenience functions for common notification types
# =============================================================================

def notify_new_match(match_id: int, user_id: int, other_group_name: str):
    """Notify user about a new match."""
    return send_notification_to_user(
        user_id=user_id,
        title="🎉 New Match!",
        body=f"You matched with {other_group_name}! Start chatting now.",
        data={'match_id': str(match_id), 'action': 'open_match'},
        notification_type='blitz_match',
    )


def notify_new_message(chat_id: int, user_id: int, sender_name: str, message_preview: str):
    """Notify user about a new message."""
    preview = message_preview[:50] + '...' if len(message_preview) > 50 else message_preview
    return send_notification_to_user(
        user_id=user_id,
        title=f"💬 {sender_name}",
        body=preview,
        data={'chat_id': str(chat_id), 'action': 'open_chat'},
        notification_type='new_message',
    )


def notify_friend_request(user_id: int, from_user_name: str):
    """Notify user about a friend request."""
    return send_notification_to_user(
        user_id=user_id,
        title="👋 Friend Request",
        body=f"{from_user_name} wants to be your friend!",
        data={'action': 'open_friends'},
        notification_type='friend_request',
    )


def notify_group_invite(user_id: int, group_name: str, inviter_name: str):
    """Notify group members when someone new joins."""
    return send_notification_to_user(
        user_id=user_id,
        title="👥 New Group Member",
        body=f"{inviter_name} joined {group_name}!",
        data={'action': 'open_groups'},
        notification_type='group_invite',
    )


def notify_blitz_expiring(user_id: int, minutes_remaining: int):
    """Notify user that their Blitz is about to expire."""
    return send_notification_to_user(
        user_id=user_id,
        title="⏰ Blitz Expiring Soon",
        body=f"Your Blitz session expires in {minutes_remaining} minutes!",
        data={'action': 'open_blitz'},
        notification_type='blitz_expiring',
    )


def notify_group_liked(user_id: int, liker_group_name: str):
    """Notify user that their group was liked."""
    return send_notification_to_user(
        user_id=user_id,
        title="❤️ Someone Likes You!",
        body=f"{liker_group_name} liked your group. Like them back to match!",
        data={'action': 'open_blitz'},
        notification_type='blitz_like',
    )


def notify_vote_request(user_id: int, group_name: str):
    """Notify user about a pending vote in their group."""
    return send_notification_to_user(
        user_id=user_id,
        title="🗳️ Vote Needed",
        body=f"Your group {group_name} needs your vote on a potential match!",
        data={'action': 'open_blitz'},
        notification_type='blitz_vote_request',
    )


def notify_meetup_proposed(user_id: int, group_name: str, location: str):
    """Notify user about a proposed meetup."""
    return send_notification_to_user(
        user_id=user_id,
        title="📍 Meetup Proposed",
        body=f"{group_name} proposed meeting at {location}",
        data={'action': 'open_matches'},
        notification_type='meetup_proposed',
    )


def notify_meetup_confirmed(user_id: int, location: str, time: str):
    """Notify user about a confirmed meetup."""
    return send_notification_to_user(
        user_id=user_id,
        title="✅ Meetup Confirmed!",
        body=f"See you at {location} - {time}",
        data={'action': 'open_matches'},
        notification_type='meetup_confirmed',
    )
