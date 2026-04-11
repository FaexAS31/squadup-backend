import logging
import re
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from drf_spectacular.utils import extend_schema

from api.models import GroupMembership, Group
from api.Serializers.group_membership_serializer import GroupMembershipSerializer
from api.Permissions.permissions import IsGroupLeader

logger = logging.getLogger('api')


@extend_schema(tags=['GroupMemberships'])
class GroupMembershipViewSet(viewsets.ModelViewSet):
    """
    Gestión de miembros en un grupo.
    
    🔒 SEGURIDAD ESTRICTA:
    - Solo el LEADER puede agregar/eliminar miembros
    - Un miembro regular NO PUEDE cambiar roles
    - No permitir que un usuario se agregue a sí mismo sin invitación
    """
    
    serializer_class = GroupMembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Un usuario solo ve memberships de grupos a los que pertenece.
        Supports ?group=<url_or_id> to filter by specific group.
        """
        user = self.request.user
        qs = GroupMembership.objects.filter(group__members=user).select_related('user')

        # Filter by specific group if provided
        group_param = self.request.query_params.get('group')
        if group_param:
            # Could be a full URL like http://…/api/groups/16/ or just an ID
            match = re.search(r'/groups/(\d+)/', group_param)
            if match:
                qs = qs.filter(group_id=int(match.group(1)))
            elif group_param.isdigit():
                qs = qs.filter(group_id=int(group_param))

        return qs
    
    def perform_create(self, serializer):
        """
        🔒 Solo el LEADER del grupo puede agregar miembros.
        """
        group_id = self.request.data.get('group')
        
        try:
            group = Group.objects.get(id=group_id)
        except Group.DoesNotExist:
            raise PermissionDenied("El grupo no existe")
        
        # Verificar que el usuario es LEADER del grupo
        is_leader = group.groupmembership_set.filter(
            user=self.request.user,
            role='admin'
        ).exists()
        
        # También permitir al creador del grupo
        is_creator = self.request.user == group.creator
        
        if not (is_leader or is_creator):
            logger.warning(
                f"Intento no autorizado de agregar miembro: "
                f"Usuario {self.request.user.id} no es LEADER de grupo {group_id}"
            )
            raise PermissionDenied("Solo el Blitz Leader puede agregar miembros")
        
        serializer.save()
        logger.info(
            f"Miembro agregado a grupo {group_id} por {self.request.user.id}"
        )
    
    def perform_update(self, serializer):
        """
        🔒 Solo el LEADER puede cambiar roles (ej. member → admin).
        """
        instance = self.get_object()
        group = instance.group
        
        # Verificar que el usuario es LEADER
        is_leader = group.groupmembership_set.filter(
            user=self.request.user,
            role='admin'
        ).exists()
        
        is_creator = self.request.user == group.creator
        
        if not (is_leader or is_creator):
            logger.warning(
                f"Intento no autorizado de cambiar rol: "
                f"Usuario {self.request.user.id} no es LEADER de grupo {group.id}"
            )
            raise PermissionDenied("Solo el Blitz Leader puede cambiar roles")
        
        # Bloquear cambio de rol del creador del grupo
        if 'role' in serializer.validated_data:
            if instance.user == group.creator:
                raise PermissionDenied(
                    "No puedes cambiar el rol del creador del grupo"
                )
        
        serializer.save()
        logger.info(
            f"Rol actualizado para miembro {instance.user.id} en grupo {group.id}"
        )
    
    def perform_destroy(self, instance):
        """
        🔒 Solo el LEADER puede eliminar miembros.
        
        PROTECCIÓN ADICIONAL: El creador del grupo NO puede ser eliminado.
        """
        group = instance.group
        
        # Verificar que el usuario es LEADER
        is_leader = group.groupmembership_set.filter(
            user=self.request.user,
            role='admin'
        ).exists()
        
        is_creator = self.request.user == group.creator
        
        if not (is_leader or is_creator):
            raise PermissionDenied("Solo el Blitz Leader puede eliminar miembros")
        
        # Proteger al creador del grupo
        if instance.user == group.creator:
            raise PermissionDenied(
                "No puedes eliminar al creador del grupo"
            )
        
        # Validación: Asegurar que el grupo tendrá al menos un LEADER
        if instance.role == 'admin':
            remaining_leaders = group.groupmembership_set.filter(
                role='admin'
            ).exclude(id=instance.id).count()
            
            if remaining_leaders == 0 and group.members.count() > 1:
                logger.error(
                    f"🔴 Intento de eliminar último LEADER del grupo {group.id}"
                )
                raise PermissionDenied(
                    "No puedes eliminar el último LEADER del grupo. "
                    "Asigna el rol admin a otro miembro primero."
                )
        
        instance.delete()
        logger.info(
            f"Miembro {instance.user.id} eliminado del grupo {group.id}"
        )
