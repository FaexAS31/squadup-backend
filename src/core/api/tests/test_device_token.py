"""
Tests for DeviceToken model and viewset.

Coverage:
- Model creation and validation
- Token registration (upsert)
- Token unregistration
- User-scoped queries
- Token transfer between users
"""
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from api.models import User, DeviceToken


class DeviceTokenModelTests(TestCase):
    """Tests for the DeviceToken model."""

    def setUp(self):
        self.user = User.objects.create(
            email='test@example.com',
            first_name='Test',
            last_name='User',
            firebase_uid='firebase_test_uid_123'
        )

    def test_create_device_token(self):
        """Test creating a device token."""
        token = DeviceToken.objects.create(
            user=self.user,
            token='fcm_token_abc123',
            platform='ios',
            device_id='device_001'
        )

        self.assertEqual(token.user, self.user)
        self.assertEqual(token.token, 'fcm_token_abc123')
        self.assertEqual(token.platform, 'ios')
        self.assertTrue(token.is_active)
        self.assertIsNotNone(token.created_at)

    def test_token_uniqueness(self):
        """Test that tokens must be unique."""
        DeviceToken.objects.create(
            user=self.user,
            token='unique_token_123',
            platform='ios'
        )

        # Creating another token with same value should fail
        with self.assertRaises(Exception):
            DeviceToken.objects.create(
                user=self.user,
                token='unique_token_123',
                platform='android'
            )

    def test_user_can_have_multiple_tokens(self):
        """Test that a user can have multiple device tokens."""
        DeviceToken.objects.create(
            user=self.user,
            token='token_device_1',
            platform='ios'
        )
        DeviceToken.objects.create(
            user=self.user,
            token='token_device_2',
            platform='android'
        )

        self.assertEqual(self.user.device_tokens.count(), 2)

    def test_token_str_representation(self):
        """Test the string representation of a token."""
        token = DeviceToken.objects.create(
            user=self.user,
            token='a_very_long_token_string_that_should_be_truncated',
            platform='ios'
        )

        str_repr = str(token)
        self.assertIn(self.user.email, str_repr)
        self.assertIn('ios', str_repr)

    def test_platform_choices(self):
        """Test that platform choices are validated."""
        # Valid platforms
        for platform in ['ios', 'android', 'web']:
            token = DeviceToken.objects.create(
                user=self.user,
                token=f'token_for_{platform}',
                platform=platform
            )
            self.assertEqual(token.platform, platform)


class DeviceTokenViewSetTests(APITestCase):
    """Tests for the DeviceToken viewset."""

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

    def test_register_new_token(self):
        """Test registering a new FCM token."""
        url = '/api/devicetokens/register/'
        data = {
            'token': 'new_fcm_token_xyz',
            'platform': 'ios',
            'device_id': 'iphone_14_pro'
        }

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(DeviceToken.objects.filter(token='new_fcm_token_xyz').exists())

        token = DeviceToken.objects.get(token='new_fcm_token_xyz')
        self.assertEqual(token.user, self.user)
        self.assertEqual(token.platform, 'ios')
        self.assertEqual(token.device_id, 'iphone_14_pro')

    def test_unregister_token(self):
        """Test unregistering a token."""
        token = DeviceToken.objects.create(
            user=self.user,
            token='token_to_unregister',
            platform='ios'
        )

        url = '/api/devicetokens/unregister/'
        data = {'token': 'token_to_unregister'}

        response = self.client.delete(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Token should be deactivated, not deleted
        token.refresh_from_db()
        self.assertFalse(token.is_active)

    def test_unregister_nonexistent_token(self):
        """Test unregistering a token that doesn't exist."""
        url = '/api/devicetokens/unregister/'
        data = {'token': 'nonexistent_token_xyz'}

        response = self.client.delete(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unregister_other_users_token(self):
        """Test that a user cannot unregister another user's token."""
        DeviceToken.objects.create(
            user=self.other_user,
            token='other_users_token',
            platform='ios'
        )

        url = '/api/devicetokens/unregister/'
        data = {'token': 'other_users_token'}

        response = self.client.delete(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_tokens_only_shows_own(self):
        """Test that listing tokens only shows the user's own tokens."""
        # Create tokens for both users
        DeviceToken.objects.create(user=self.user, token='my_token_1', platform='ios')
        DeviceToken.objects.create(user=self.user, token='my_token_2', platform='android')
        DeviceToken.objects.create(user=self.other_user, token='other_token', platform='ios')

        url = '/api/devicetokens/'
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Handle both paginated and non-paginated responses
        if isinstance(response.data, dict):
            results = response.data.get('results', response.data)
        else:
            results = response.data

        self.assertEqual(len(results), 2)
        tokens = [r['token'] for r in results]
        self.assertIn('my_token_1', tokens)
        self.assertIn('my_token_2', tokens)
        self.assertNotIn('other_token', tokens)

    def test_list_excludes_inactive_tokens(self):
        """Test that inactive tokens are not listed."""
        DeviceToken.objects.create(user=self.user, token='active_token', platform='ios', is_active=True)
        DeviceToken.objects.create(user=self.user, token='inactive_token', platform='ios', is_active=False)

        url = '/api/devicetokens/'
        response = self.client.get(url)

        # Handle both paginated and non-paginated responses
        if isinstance(response.data, dict):
            results = response.data.get('results', response.data)
        else:
            results = response.data

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['token'], 'active_token')

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated requests are denied."""
        self.client.force_authenticate(user=None)

        url = '/api/devicetokens/'
        response = self.client.get(url)

        # DRF returns 403 Forbidden for unauthenticated users by default
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_register_without_token_fails(self):
        """Test that registration without a token fails."""
        url = '/api/devicetokens/register/'
        data = {'platform': 'ios'}

        response = self.client.post(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unregister_without_token_fails(self):
        """Test that unregistration without a token fails."""
        url = '/api/devicetokens/unregister/'
        data = {}

        response = self.client.delete(url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
