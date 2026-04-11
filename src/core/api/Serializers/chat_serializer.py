from rest_framework import serializers
from api.models import Chat


class ChatSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    # Read-only computed fields for chat display
    match_name = serializers.SerializerMethodField()
    match_id = serializers.SerializerMethodField()
    participant_count = serializers.IntegerField(read_only=True)
    unread_count = serializers.SerializerMethodField()
    is_solo = serializers.SerializerMethodField()
    solo_match_id = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = '__all__'

    def get_match_name(self, obj):
        """Return a display name: 'Group1 & Group2', solo partner name, or participant names."""
        request = self.context.get('request')
        current_user = request.user if request else None

        # Solo mode chats: show partner name
        if obj.metadata.get('solo_mode') and current_user:
            partner = obj.participants.exclude(id=current_user.id).first()
            if partner:
                name = f"{partner.first_name or ''} {partner.last_name or ''}".strip()
                return name or partner.email

        # Group blitz chats: show "Group1 & Group2"
        try:
            match = getattr(obj, 'match', None)
            if match:
                group1_name = match.blitz_1.group.name if match.blitz_1 and match.blitz_1.group else 'Grupo'
                group2_name = match.blitz_2.group.name if match.blitz_2 and match.blitz_2.group else 'Grupo'
                return f"{group1_name} & {group2_name}"
        except Exception:
            pass

        # Fallback: participant names (excluding current user)
        if current_user:
            others = obj.participants.exclude(id=current_user.id)[:3]
            names = []
            for u in others:
                name = f"{u.first_name or ''} {u.last_name or ''}".strip()
                names.append(name or u.email)
            total = obj.participants.exclude(id=current_user.id).count()
            if names:
                result = ', '.join(names)
                if total > 3:
                    result += f' y {total - 3} más'
                return result

        return f"Chat {obj.id}"

    def get_match_id(self, obj):
        """Return the match ID for navigation."""
        try:
            match = getattr(obj, 'match', None)
            if match:
                return match.id
        except Exception:
            pass
        return None

    def get_unread_count(self, obj):
        """Count unread messages for the current user in this chat."""
        request = self.context.get('request')
        if not request or not request.user:
            return 0
        return obj.messages.filter(is_read=False).exclude(sender=request.user).count()

    def get_is_solo(self, obj):
        return bool(obj.metadata.get('solo_mode'))

    def get_solo_match_id(self, obj):
        if not obj.metadata.get('solo_mode'):
            return None
        sm = obj.solo_matches.first()
        return sm.id if sm else None

    def get_group_id(self, obj):
        if not obj.metadata.get('solo_mode'):
            return None
        sm = obj.solo_matches.select_related('group').first()
        return sm.group_id if sm and sm.group_id else None
