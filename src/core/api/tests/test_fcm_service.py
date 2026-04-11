"""
Tests for FCM service.

Coverage:
- Single notification sending
- Batch notification sending
- User notification with DB record
- Token deactivation on errors
- Convenience notification functions
"""
from django.test import TestCase
from django.utils import timezone
from unittest.mock import patch, MagicMock

from api.models import User, DeviceToken, Notification


class FCMServiceTests(TestCase):
    """Tests for the FCM service functions."""

    def setUp(self):
        self.user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            firebase_uid='firebase_test_uid_123'
        )
        self.token1 = DeviceToken.objects.create(
            user=self.user,
            token='fcm_token_1',
            platform='ios',
            is_active=True
        )
        self.token2 = DeviceToken.objects.create(
            user=self.user,
            token='fcm_token_2',
            platform='android',
            is_active=True
        )

    @patch('utils.fcm_service._get_firebase_app')
    @patch('utils.fcm_service.messaging')
    def test_send_push_notification_success(self, mock_messaging, mock_get_app):
        """Test sending a single push notification successfully."""
        from utils.fcm_service import send_push_notification

        mock_get_app.return_value = MagicMock()
        mock_messaging.send.return_value = 'message_id_123'

        result = send_push_notification(
            token='test_token',
            title='Test Title',
            body='Test Body',
            data={'key': 'value'}
        )

        self.assertTrue(result)
        mock_messaging.send.assert_called_once()

    @patch('utils.fcm_service._get_firebase_app')
    def test_send_push_notification_no_firebase_app(self, mock_get_app):
        """Test that notification fails gracefully when Firebase app is not available."""
        from utils.fcm_service import send_push_notification

        mock_get_app.return_value = None

        result = send_push_notification(
            token='test_token',
            title='Test Title',
            body='Test Body'
        )

        self.assertFalse(result)

    @patch('utils.fcm_service._get_firebase_app')
    @patch('utils.fcm_service.messaging')
    def test_send_push_notification_batch_success(self, mock_messaging, mock_get_app):
        """Test sending batch notifications successfully."""
        from utils.fcm_service import send_push_notification_batch

        mock_get_app.return_value = MagicMock()

        # Mock batch response
        mock_response = MagicMock()
        mock_response.success_count = 2
        mock_response.failure_count = 0
        mock_response.responses = [
            MagicMock(success=True),
            MagicMock(success=True)
        ]
        mock_messaging.send_each_for_multicast.return_value = mock_response

        result = send_push_notification_batch(
            tokens=['token1', 'token2'],
            title='Test Title',
            body='Test Body'
        )

        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['failure_count'], 0)
        self.assertEqual(result['failed_tokens'], [])

    @patch('utils.fcm_service._get_firebase_app')
    @patch('utils.fcm_service.messaging')
    def test_send_push_notification_batch_tracks_failed_tokens(self, mock_messaging, mock_get_app):
        """Test that batch notifications track failed tokens."""
        from utils.fcm_service import send_push_notification_batch

        mock_get_app.return_value = MagicMock()

        # Mock batch response with failures (don't test isinstance deactivation)
        mock_response = MagicMock()
        mock_response.success_count = 1
        mock_response.failure_count = 1
        mock_response.responses = [
            MagicMock(success=True, exception=None),
            MagicMock(success=False, exception=None)  # Failed but no exception
        ]
        mock_messaging.send_each_for_multicast.return_value = mock_response

        result = send_push_notification_batch(
            tokens=['token1', 'failed_token'],
            title='Test Title',
            body='Test Body'
        )

        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['failure_count'], 1)
        self.assertIn('failed_token', result['failed_tokens'])

    @patch('utils.fcm_service._get_firebase_app')
    def test_send_push_notification_batch_no_firebase_app(self, mock_get_app):
        """Test that batch notification fails gracefully when Firebase app is not available."""
        from utils.fcm_service import send_push_notification_batch

        mock_get_app.return_value = None

        result = send_push_notification_batch(
            tokens=['token1', 'token2'],
            title='Test Title',
            body='Test Body'
        )

        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failure_count'], 2)

    @patch('utils.fcm_service._get_firebase_app')
    def test_send_push_notification_batch_empty_tokens(self, mock_get_app):
        """Test batch notification with empty token list."""
        from utils.fcm_service import send_push_notification_batch

        mock_get_app.return_value = MagicMock()

        result = send_push_notification_batch(
            tokens=[],
            title='Test Title',
            body='Test Body'
        )

        self.assertEqual(result['success_count'], 0)
        self.assertEqual(result['failure_count'], 0)

    @patch('utils.fcm_service.send_push_notification_batch')
    def test_send_notification_to_user_creates_db_record(self, mock_batch):
        """Test that sending notification to user creates a database record."""
        from utils.fcm_service import send_notification_to_user

        mock_batch.return_value = {
            'success_count': 2,
            'failure_count': 0,
            'failed_tokens': []
        }

        result = send_notification_to_user(
            user_id=self.user.id,
            title='Test Title',
            body='Test Body',
            notification_type='BLITZ_MATCH',
            data={'match_id': '123'}
        )

        self.assertEqual(result['sent_count'], 2)
        self.assertIsNotNone(result['notification_id'])

        # Verify notification was created in DB
        notification = Notification.objects.get(id=result['notification_id'])
        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.title, 'Test Title')
        self.assertEqual(notification.notification_type, 'BLITZ_MATCH')
        self.assertTrue(notification.fcm_sent)
        self.assertIsNotNone(notification.fcm_sent_at)

    @patch('utils.fcm_service.send_push_notification_batch')
    def test_send_notification_to_user_without_tokens(self, mock_batch):
        """Test sending notification to user with no registered tokens."""
        from utils.fcm_service import send_notification_to_user

        # Remove all tokens
        DeviceToken.objects.filter(user=self.user).delete()

        result = send_notification_to_user(
            user_id=self.user.id,
            title='Test Title',
            body='Test Body'
        )

        # Should still create DB record
        self.assertIsNotNone(result['notification_id'])
        self.assertEqual(result['sent_count'], 0)

        # Batch should not be called since no tokens
        mock_batch.assert_not_called()

    @patch('utils.fcm_service.send_push_notification_batch')
    def test_send_notification_to_user_skip_db(self, mock_batch):
        """Test sending notification without saving to database."""
        from utils.fcm_service import send_notification_to_user

        mock_batch.return_value = {
            'success_count': 1,
            'failure_count': 0,
            'failed_tokens': []
        }

        initial_count = Notification.objects.count()

        result = send_notification_to_user(
            user_id=self.user.id,
            title='Test Title',
            body='Test Body',
            save_to_db=False
        )

        self.assertIsNone(result['notification_id'])
        self.assertEqual(Notification.objects.count(), initial_count)

    def test_deactivate_token(self):
        """Test that deactivating a token marks it as inactive."""
        from utils.fcm_service import _deactivate_token

        self.assertTrue(self.token1.is_active)

        _deactivate_token(self.token1.token)

        self.token1.refresh_from_db()
        self.assertFalse(self.token1.is_active)


class FCMConvenienceFunctionTests(TestCase):
    """Tests for FCM convenience notification functions."""

    def setUp(self):
        self.user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            firebase_uid='firebase_test_uid_123'
        )
        DeviceToken.objects.create(
            user=self.user,
            token='test_token',
            platform='ios',
            is_active=True
        )

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_new_match(self, mock_send):
        """Test the notify_new_match convenience function."""
        from utils.fcm_service import notify_new_match

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_new_match(
            match_id=123,
            user_id=self.user.id,
            other_group_name='Team Alpha'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['user_id'], self.user.id)
        self.assertEqual(call_kwargs['notification_type'], 'BLITZ_MATCH')
        self.assertIn('Team Alpha', call_kwargs['body'])
        self.assertEqual(call_kwargs['data']['match_id'], '123')

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_new_message(self, mock_send):
        """Test the notify_new_message convenience function."""
        from utils.fcm_service import notify_new_message

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_new_message(
            chat_id=456,
            user_id=self.user.id,
            sender_name='John',
            message_preview='Hey, how are you doing today?'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'NEW_MESSAGE')
        self.assertIn('John', call_kwargs['title'])
        self.assertEqual(call_kwargs['data']['chat_id'], '456')

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_new_message_truncates_long_preview(self, mock_send):
        """Test that long message previews are truncated."""
        from utils.fcm_service import notify_new_message

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        long_message = 'A' * 100  # 100 characters

        result = notify_new_message(
            chat_id=456,
            user_id=self.user.id,
            sender_name='John',
            message_preview=long_message
        )

        call_kwargs = mock_send.call_args[1]
        # Should be truncated to 50 chars + '...'
        self.assertLessEqual(len(call_kwargs['body']), 53)
        self.assertTrue(call_kwargs['body'].endswith('...'))

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_friend_request(self, mock_send):
        """Test the notify_friend_request convenience function."""
        from utils.fcm_service import notify_friend_request

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_friend_request(
            user_id=self.user.id,
            from_user_name='Jane'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'FRIEND_REQUEST')
        self.assertIn('Jane', call_kwargs['body'])

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_group_invite(self, mock_send):
        """Test the notify_group_invite convenience function."""
        from utils.fcm_service import notify_group_invite

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_group_invite(
            user_id=self.user.id,
            group_name='Weekend Warriors',
            inviter_name='Mike'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'GROUP_INVITE')
        self.assertIn('Weekend Warriors', call_kwargs['body'])
        self.assertIn('Mike', call_kwargs['body'])

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_blitz_expiring(self, mock_send):
        """Test the notify_blitz_expiring convenience function."""
        from utils.fcm_service import notify_blitz_expiring

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_blitz_expiring(
            user_id=self.user.id,
            minutes_remaining=10
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'BLITZ_EXPIRING')
        self.assertIn('10 minutes', call_kwargs['body'])

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_group_liked(self, mock_send):
        """Test the notify_group_liked convenience function."""
        from utils.fcm_service import notify_group_liked

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_group_liked(
            user_id=self.user.id,
            liker_group_name='Cool Kids'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'BLITZ_LIKE')
        self.assertIn('Cool Kids', call_kwargs['body'])

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_vote_request(self, mock_send):
        """Test the notify_vote_request convenience function."""
        from utils.fcm_service import notify_vote_request

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_vote_request(
            user_id=self.user.id,
            group_name='My Squad'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'BLITZ_VOTE_REQUEST')
        self.assertIn('My Squad', call_kwargs['body'])

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_meetup_proposed(self, mock_send):
        """Test the notify_meetup_proposed convenience function."""
        from utils.fcm_service import notify_meetup_proposed

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_meetup_proposed(
            user_id=self.user.id,
            group_name='Team Beta',
            location='Central Park'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'MEETUP_PROPOSED')
        self.assertIn('Central Park', call_kwargs['body'])

    @patch('utils.fcm_service.send_notification_to_user')
    def test_notify_meetup_confirmed(self, mock_send):
        """Test the notify_meetup_confirmed convenience function."""
        from utils.fcm_service import notify_meetup_confirmed

        mock_send.return_value = {'sent_count': 1, 'notification_id': 1}

        result = notify_meetup_confirmed(
            user_id=self.user.id,
            location='Coffee Shop',
            time='3:00 PM'
        )

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs['notification_type'], 'MEETUP_CONFIRMED')
        self.assertIn('Coffee Shop', call_kwargs['body'])
        self.assertIn('3:00 PM', call_kwargs['body'])
