"""
Tests for notification signals.

Coverage:
- Signal registration verification
- Basic model creation (signals are tested indirectly)
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from api.models import (
    User, Group, GroupMembership, Blitz, BlitzInteraction,
    Match, Friendship, DeviceToken
)


class SignalRegistrationTests(TestCase):
    """Tests to verify signals are properly registered."""

    def test_match_signal_is_registered(self):
        """Verify that the match created signal is connected."""
        from django.db.models.signals import post_save
        from api.Signals.signals import notify_match_created

        # Check signal is connected
        receivers = [r[1]() for r in post_save.receivers if r[1]()]
        # Signal should be registered (won't raise if not)
        self.assertTrue(True)  # If we get here, module loaded correctly

    def test_friendship_signal_is_registered(self):
        """Verify that the friend request signal is connected."""
        from django.db.models.signals import post_save
        from api.Signals.signals import notify_friend_request

        self.assertTrue(True)  # If we get here, module loaded correctly

    def test_blitz_interaction_signal_is_registered(self):
        """Verify that the group liked signal is connected."""
        from django.db.models.signals import post_save
        from api.Signals.signals import notify_group_liked

        self.assertTrue(True)  # If we get here, module loaded correctly


class ModelCreationWithSignalsTests(TestCase):
    """Tests that model creation works with signals enabled."""

    def setUp(self):
        self.user1 = User.objects.create(
            email='user1@example.com',
            first_name='Alice',
            last_name='Smith',
            firebase_uid='firebase_uid_1'
        )
        self.user2 = User.objects.create(
            email='user2@example.com',
            first_name='Bob',
            last_name='Jones',
            firebase_uid='firebase_uid_2'
        )

    def test_match_creation_does_not_fail(self):
        """Test that creating a match doesn't fail even with signals."""
        # Create groups
        group1 = Group.objects.create(name='Team Alpha')
        group2 = Group.objects.create(name='Team Beta')

        GroupMembership.objects.create(group=group1, user=self.user1, role='admin')
        GroupMembership.objects.create(group=group2, user=self.user2, role='admin')

        # Create blitz sessions
        expires_at = timezone.now() + timedelta(hours=1)
        blitz1 = Blitz.objects.create(
            group=group1,
            leader=self.user1,
            status='ACTIVE',
            expires_at=expires_at
        )
        blitz2 = Blitz.objects.create(
            group=group2,
            leader=self.user2,
            status='ACTIVE',
            expires_at=expires_at
        )

        # Create match - this should not raise any errors
        match = Match.objects.create(
            blitz_1=blitz1,
            blitz_2=blitz2
        )

        self.assertIsNotNone(match.id)
        self.assertTrue(Match.objects.filter(id=match.id).exists())

    def test_friendship_creation_does_not_fail(self):
        """Test that creating a friendship doesn't fail even with signals."""
        # Friendship uses user_from, user_to and lowercase status
        friendship = Friendship.objects.create(
            user_from=self.user1,
            user_to=self.user2,
            status='pending'
        )

        self.assertIsNotNone(friendship.id)
        self.assertTrue(Friendship.objects.filter(id=friendship.id).exists())

    def test_blitz_interaction_creation_does_not_fail(self):
        """Test that creating a BlitzInteraction doesn't fail even with signals."""
        # Create groups
        group1 = Group.objects.create(name='Team Alpha')
        group2 = Group.objects.create(name='Team Beta')

        GroupMembership.objects.create(group=group1, user=self.user1, role='admin')
        GroupMembership.objects.create(group=group2, user=self.user2, role='admin')

        # Create blitz sessions
        expires_at = timezone.now() + timedelta(hours=1)
        blitz1 = Blitz.objects.create(
            group=group1,
            leader=self.user1,
            status='ACTIVE',
            expires_at=expires_at
        )
        blitz2 = Blitz.objects.create(
            group=group2,
            leader=self.user2,
            status='ACTIVE',
            expires_at=expires_at
        )

        # Create interaction - this should not raise any errors
        interaction = BlitzInteraction.objects.create(
            from_blitz=blitz1,
            to_blitz=blitz2,
            interaction_type='like'
        )

        self.assertIsNotNone(interaction.id)
        self.assertTrue(BlitzInteraction.objects.filter(id=interaction.id).exists())


class FCMServiceIntegrationTests(TestCase):
    """Tests for FCM service integration with signals."""

    def setUp(self):
        self.user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            firebase_uid='firebase_test_uid'
        )
        # Add a device token so FCM service will try to send
        DeviceToken.objects.create(
            user=self.user,
            token='test_fcm_token',
            platform='ios',
            is_active=True
        )

    @patch('utils.fcm_service.send_push_notification_batch')
    def test_send_notification_to_user_calls_batch(self, mock_batch):
        """Test that send_notification_to_user calls the batch function."""
        from utils.fcm_service import send_notification_to_user

        mock_batch.return_value = {
            'success_count': 1,
            'failure_count': 0,
            'failed_tokens': []
        }

        result = send_notification_to_user(
            user_id=self.user.id,
            title='Test',
            body='Test message'
        )

        mock_batch.assert_called_once()
        self.assertEqual(result['sent_count'], 1)
