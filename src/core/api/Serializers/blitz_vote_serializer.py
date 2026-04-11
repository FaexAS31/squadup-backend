from rest_framework import serializers
from api.models import BlitzVote


class BlitzVoteSerializer(serializers.HyperlinkedModelSerializer):
    id = serializers.ReadOnlyField()
    target_group_name = serializers.SerializerMethodField()
    target_group_image = serializers.SerializerMethodField()
    proposer_name = serializers.SerializerMethodField()
    consensus_status = serializers.SerializerMethodField()

    class Meta:
        model = BlitzVote
        fields = '__all__'

    def get_target_group_name(self, obj):
        try:
            return obj.interaction.to_blitz.group.name
        except Exception:
            return None

    def get_target_group_image(self, obj):
        try:
            return obj.interaction.to_blitz.group.image_url
        except Exception:
            return None

    def get_proposer_name(self, obj):
        """Name of the user who proposed the like (first approved vote)."""
        try:
            proposer_vote = obj.interaction.votes.filter(
                vote='approved',
            ).order_by('voted_at').first()
            if proposer_vote:
                return proposer_vote.user.first_name or proposer_vote.user.email
        except Exception:
            pass
        return None

    def get_consensus_status(self, obj):
        try:
            return obj.interaction.consensus_status
        except Exception:
            return None
