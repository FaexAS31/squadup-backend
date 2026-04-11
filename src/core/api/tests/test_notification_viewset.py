"""
Tests for Notification viewset.

Coverage:
- List notifications (user-scoped)
- Mark single notification as read
- Mark all notifications as read
- Get unread count
- Filter by read/unread status
- Filter by notification type
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from api.models import User, Notification


def get_results(response_data):
    """Helper to extract results from paginated or non-paginated responses."""
    if isinstance(response_data, dict):
        return response_data.get('results', response_data)
    return response_data


class NotificationViewSetTests(APITestCase):
    """Tests for the Notification viewset."""

    def setUp(self):
        self.user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            firebase_uid='firebase_test_uid_123'
        )
        self.other_user = User.objects.create(
            email='other@example.com',
            first_name='Other',
            last_name='User',
            firebase_uid='firebase_other_uid_456'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create test notifications
        self.notification1 = Notification.objects.create(
            user=self.user,
            notification_type='BLITZ_MATCH',
            title='New Match!',
            body='You matched with Team Alpha',
            is_read=False
        )
        self.notification2 = Notification.objects.create(
            user=self.user,
            notification_type='NEW_MESSAGE',
            title='New Message',
            body='Hey, how are you?',
            is_read=True
        )
        self.notification3 = Notification.objects.create(
            user=self.user,
            notification_type='FRIEND_REQUEST',
            title='Friend Request',
            body='John wants to be your friend',
            is_read=False
        )
        # Other user's notification
        self.other_notification = Notification.objects.create(
            user=self.other_user,
            notification_type='BLITZ_MATCH',
            title='Their Match',
            body='Should not see this',
            is_read=False
        )

    def test_list_notifications_only_shows_own(self):
        """Test that listing notifications only shows the user's own notifications."""
        url = '/api/notifications/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = get_results(response.data)
        self.assertEqual(len(results), 3)

        # Should not include other user's notification
        titles = [n['title'] for n in results]
        self.assertNotIn('Their Match', titles)

    def test_list_notifications_ordered_by_created_at(self):
        """Test that notifications are ordered by creation date (newest first)."""
        url = '/api/notifications/'
        response = self.client.get(url)

        results = get_results(response.data)

        # Most recent should be first
        self.assertEqual(results[0]['title'], 'Friend Request')

    def test_filter_by_read_status_unread(self):
        """Test filtering notifications by unread status."""
        url = '/api/notifications/?is_read=false'
        response = self.client.get(url)

        results = get_results(response.data)
        self.assertEqual(len(results), 2)

        for notification in results:
            self.assertFalse(notification['is_read'])

    def test_filter_by_read_status_read(self):
        """Test filtering notifications by read status."""
        url = '/api/notifications/?is_read=true'
        response = self.client.get(url)

        results = get_results(response.data)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['is_read'])

    def test_filter_by_notification_type(self):
        """Test filtering notifications by type."""
        url = '/api/notifications/?type=BLITZ_MATCH'
        response = self.client.get(url)

        results = get_results(response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['notification_type'], 'BLITZ_MATCH')

    def test_mark_single_notification_as_read(self):
        """Test marking a single notification as read."""
        url = f'/api/notifications/{self.notification1.id}/mark-read/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.notification1.refresh_from_db()
        self.assertTrue(self.notification1.is_read)
        self.assertIsNotNone(self.notification1.read_at)

    def test_mark_already_read_notification(self):
        """Test marking an already read notification doesn't change read_at."""
        # First mark as read
        self.notification1.is_read = True
        self.notification1.read_at = timezone.now()
        self.notification1.save()
        original_read_at = self.notification1.read_at

        url = f'/api/notifications/{self.notification1.id}/mark-read/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.notification1.refresh_from_db()
        self.assertTrue(self.notification1.is_read)
        # read_at should not change
        self.assertEqual(self.notification1.read_at, original_read_at)

    def test_cannot_mark_other_users_notification_as_read(self):
        """Test that a user cannot mark another user's notification as read."""
        url = f'/api/notifications/{self.other_notification.id}/mark-read/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.other_notification.refresh_from_db()
        self.assertFalse(self.other_notification.is_read)

    def test_mark_all_notifications_as_read(self):
        """Test marking all notifications as read."""
        url = '/api/notifications/mark-all-read/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['updated_count'], 2)  # 2 were unread

        # Verify all are now read
        self.notification1.refresh_from_db()
        self.notification3.refresh_from_db()
        self.assertTrue(self.notification1.is_read)
        self.assertTrue(self.notification3.is_read)

        # Other user's notification should not be affected
        self.other_notification.refresh_from_db()
        self.assertFalse(self.other_notification.is_read)

    def test_mark_all_read_when_none_unread(self):
        """Test marking all as read when there are no unread notifications."""
        # Mark all as read first
        Notification.objects.filter(user=self.user).update(is_read=True)

        url = '/api/notifications/mark-all-read/'
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['updated_count'], 0)

    def test_get_unread_count(self):
        """Test getting the count of unread notifications."""
        url = '/api/notifications/unread-count/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['unread_count'], 2)

    def test_get_unread_count_after_marking_read(self):
        """Test that unread count updates after marking notifications as read."""
        # Mark all as read
        Notification.objects.filter(user=self.user).update(is_read=True)

        url = '/api/notifications/unread-count/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['unread_count'], 0)

    def test_delete_own_notification(self):
        """Test deleting own notification."""
        url = f'/api/notifications/{self.notification1.id}/'
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Notification.objects.filter(id=self.notification1.id).exists())

    def test_get_notification_detail(self):
        """Test getting a single notification's details."""
        url = f'/api/notifications/{self.notification1.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'New Match!')
        self.assertEqual(response.data['notification_type'], 'BLITZ_MATCH')

    def test_cannot_get_other_users_notification(self):
        """Test that a user cannot view another user's notification."""
        url = f'/api/notifications/{self.other_notification.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated requests are denied."""
        self.client.force_authenticate(user=None)

        url = '/api/notifications/'
        response = self.client.get(url)

        # DRF returns 403 Forbidden for unauthenticated users by default
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_notification_fcm_fields_returned(self):
        """Test that FCM-related fields are included in response."""
        url = f'/api/notifications/{self.notification1.id}/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('fcm_sent', response.data)
        self.assertIn('fcm_sent_at', response.data)


class NotificationModelTests(TestCase):
    """Tests for the Notification model."""

    def setUp(self):
        self.user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            firebase_uid='firebase_test_uid_123'
        )

    def test_create_notification(self):
        """Test creating a notification."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type='BLITZ_MATCH',
            title='Test Title',
            body='Test Body',
            data={'match_id': 123}
        )

        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.notification_type, 'BLITZ_MATCH')
        self.assertFalse(notification.is_read)
        self.assertFalse(notification.fcm_sent)
        self.assertIsNone(notification.read_at)
        self.assertIsNone(notification.fcm_sent_at)

    def test_notification_type_choices(self):
        """Test that all notification types are valid."""
        valid_types = [
            'BLITZ_MATCH', 'BLITZ_LIKE', 'BLITZ_VOTE_REQUEST',
            'NEW_MESSAGE', 'FRIEND_REQUEST', 'GROUP_INVITE',
            'MEETUP_PROPOSED', 'MEETUP_CONFIRMED', 'BLITZ_EXPIRING', 'SYSTEM'
        ]

        for ntype in valid_types:
            notification = Notification.objects.create(
                user=self.user,
                notification_type=ntype,
                title=f'Test {ntype}',
                body='Test body'
            )
            self.assertEqual(notification.notification_type, ntype)

    def test_notification_str_representation(self):
        """Test the string representation of a notification."""
        notification = Notification.objects.create(
            user=self.user,
            notification_type='BLITZ_MATCH',
            title='Match Found',
            body='Test body'
        )

        str_repr = str(notification)
        self.assertIn('BLITZ_MATCH', str_repr)
        self.assertIn('Match Found', str_repr)

    def test_notification_data_json_field(self):
        """Test that the data field properly stores JSON."""
        complex_data = {
            'match_id': 123,
            'groups': ['Team A', 'Team B'],
            'nested': {'key': 'value'}
        }

        notification = Notification.objects.create(
            user=self.user,
            notification_type='BLITZ_MATCH',
            title='Test',
            body='Test',
            data=complex_data
        )

        notification.refresh_from_db()
        self.assertEqual(notification.data, complex_data)
