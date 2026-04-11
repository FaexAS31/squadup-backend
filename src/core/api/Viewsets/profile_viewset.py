import logging
from rest_framework import viewsets
from drf_spectacular.utils import extend_schema
from api.models import Profile
from api.Serializers.profile_serializer import ProfileSerializer

logger = logging.getLogger('api')

@extend_schema(tags=['Profiles'])
class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer

    def update(self, request, *args, **kwargs):
        logger.info(f"Updating profile ID {kwargs.get('pk')}. Requesting user: {request.user}")
        try:
            return super().update(request, *args, **kwargs)
        except Exception as e:
            logger.warning(f"Validation or save error in Profile: {str(e)}")
            raise e