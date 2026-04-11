from rest_framework import serializers
from api.models import Blitz, GroupMembership, ProfilePhoto
from django.utils import timezone
from datetime import timedelta


class BlitzSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()

    # Write-only fields to accept the frontend's payload format
    activities = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    duration_minutes = serializers.IntegerField(write_only=True, required=False)

    # Read-only computed fields for swipe cards
    group_name = serializers.SerializerMethodField()
    group_description = serializers.SerializerMethodField()
    group_interests = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    group_image = serializers.SerializerMethodField()
    members_preview = serializers.SerializerMethodField()

    class Meta:
        model = Blitz
        fields = '__all__'
        extra_kwargs = {
            'leader': {'required': False},
            'status': {'required': False},
        }

    def get_group_name(self, obj):
        return obj.group.name if obj.group else None

    def get_group_description(self, obj):
        return obj.group.description if obj.group else ''

    def get_group_interests(self, obj):
        if not obj.group:
            return []
        return list(obj.group.combined_interests)[:10]

    def get_member_count(self, obj):
        return obj.group.member_count if obj.group else 0

    def get_group_image(self, obj):
        return obj.group.image_url if obj.group else None

    def get_members_preview(self, obj):
        """Return group members with basic info for swipe cards."""
        if not obj.group:
            return []
        memberships = GroupMembership.objects.filter(
            group=obj.group
        ).select_related('user', 'user__profile')[:6]
        result = []
        for m in memberships:
            u = m.user
            bio = ''
            interests = []
            try:
                bio = u.profile.bio or ''
                interests = u.profile.interests or []
            except Exception:
                pass
            gallery = ProfilePhoto.objects.filter(
                user=u
            ).order_by('order')[:6]
            gallery_photos = [
                {'url': p.image_url, 'thumbnail': p.thumbnail_url}
                for p in gallery
            ]
            result.append({
                'first_name': u.first_name,
                'profile_photo': u.profile_photo or '',
                'bio': bio,
                'interests': interests,
                'gallery_photos': gallery_photos,
            })
        return result

    def create(self, validated_data):
        activities = validated_data.pop('activities', [])
        duration = validated_data.pop('duration_minutes', None)

        # Map activities array → activity_type (first item) + metadata
        if activities:
            validated_data['activity_type'] = activities[0]
        if len(activities) > 1:
            validated_data.setdefault('metadata', {})['activities'] = activities

        # Set leader from request user
        validated_data['leader'] = self.context['request'].user

        # Ensure min_opponent_size defaults (NOT NULL in DB)
        validated_data.setdefault('min_opponent_size', 2)

        # Ensure max >= min when both are set
        min_size = validated_data.get('min_opponent_size', 2)
        max_size = validated_data.get('max_opponent_size')
        if max_size is not None and max_size < min_size:
            validated_data['max_opponent_size'] = min_size

        # Set expiration from duration_minutes (overrides model default)
        if duration:
            validated_data['expires_at'] = timezone.now() + timedelta(minutes=duration)

        return super().create(validated_data)
