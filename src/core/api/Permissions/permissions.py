"""
Custom permission classes para SquadUp.

🔒 Usar estos permisos en todos los ViewSets para garantizar consistencia de seguridad.
"""

from rest_framework.permissions import BasePermission
from api.models import User


class IsOwner(BasePermission):
    """
    Permiso: El usuario es propietario del objeto.
    
    Funciona para cualquier objeto con:
    - Atributo 'id' y requiere obj.id == request.user.id
    - Atributo 'user' (ForeignKey) y requiere obj.user == request.user
    - Atributo 'created_by' (ForeignKey) y requiere obj.created_by == request.user
    """
    
    def has_object_permission(self, request, view, obj):
        # Para User
        if hasattr(obj, 'id') and not hasattr(obj, 'user') and not hasattr(obj, 'created_by'):
            return obj.id == request.user.id
        
        # Para otros modelos con user/owner FK
        if hasattr(obj, 'user'):
            return obj.user == request.user
        
        if hasattr(obj, 'created_by'):
            return obj.created_by == request.user
        
        return False


class IsGroupLeader(BasePermission):
    """
    Permiso: El usuario es LEADER (admin) del grupo.
    
    Valida que request.user sea miembro con rol 'admin' en obj.group.
    """
    
    def has_object_permission(self, request, view, obj):
        # Para Group
        if hasattr(obj, 'groupmembership_set'):
            is_leader = obj.groupmembership_set.filter(
                user=request.user,
                role='admin'
            ).exists()
            return is_leader
        
        # Para objetos que tienen group FK (ej. Blitz)
        if hasattr(obj, 'group'):
            is_leader = obj.group.groupmembership_set.filter(
                user=request.user,
                role='admin'
            ).exists()
            return is_leader
        
        return False


class IsGroupMember(BasePermission):
    """
    Permiso: El usuario es miembro del grupo.
    
    Valida que request.user esté en obj.group.members.
    """
    
    def has_object_permission(self, request, view, obj):
        # Para Group
        if hasattr(obj, 'members'):
            return obj.members.filter(id=request.user.id).exists()
        
        # Para objetos que tienen group FK
        if hasattr(obj, 'group'):
            return obj.group.members.filter(id=request.user.id).exists()
        
        return False


class IsAdmin(BasePermission):
    """
    Permiso: El usuario es ADMIN del sistema.
    
    Verifica que request.user.role == User.Roles.ADMIN
    """
    
    def has_permission(self, request, view):
        return (
            request.user 
            and request.user.is_authenticated 
            and request.user.role == User.Roles.ADMIN
        )


class IsChatParticipant(BasePermission):
    """
    Permiso: El usuario es participante del chat.
    
    Valida que request.user esté en obj.participants.
    """
    
    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'chat'):
            # Para Message
            return obj.chat.participants.filter(id=request.user.id).exists()
        elif hasattr(obj, 'participants'):
            # Para Chat
            return obj.participants.filter(id=request.user.id).exists()
        
        return False


class IsMatchParticipant(BasePermission):
    """
    Permiso: El usuario es participante del match.
    
    Valida que request.user esté en blitz_1.group O blitz_2.group.
    """
    
    def has_object_permission(self, request, view, obj):
        if hasattr(obj, 'blitz_1') and hasattr(obj, 'blitz_2'):
            # Verificar si el usuario está en alguno de los dos grupos
            in_group_1 = obj.blitz_1.group.members.filter(
                id=request.user.id
            ).exists()
            in_group_2 = obj.blitz_2.group.members.filter(
                id=request.user.id
            ).exists()
            
            return in_group_1 or in_group_2
        
        return False


