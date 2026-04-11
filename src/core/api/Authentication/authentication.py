from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
import firebase_admin
from firebase_admin import credentials, auth
from django.conf import settings
from api.models import User
import logging

logger = logging.getLogger(__name__)

# Inicializar Firebase si no está inicializado
try:
    firebase_admin.get_app()
    logger.info("Firebase already initialized")
except ValueError:
    creds_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)

    import os
    if os.path.exists(creds_path):
        cred = credentials.Certificate(creds_path)
        firebase_admin.initialize_app(cred)
        logger.info(f"Firebase initialized from: {creds_path}")
    else:
        logger.error(
            f"Firebase credentials not found at {creds_path}. "
            "Set FIREBASE_SERVICE_ACCOUNT_PATH env var or download from Firebase Console."
        )


class FirebaseAuthentication(BaseAuthentication):
    """
     Autenticación con Firebase ID Token.
     Crea automáticamente el usuario en Django si no existe.
    
    Formato esperado en header:
    Authorization: Bearer {firebase_id_token}
    """
    
    def authenticate(self, request):
        """
        Autentica usando Firebase ID Token del header Authorization.
        Retorna (user, None) si autenticación es exitosa.
        Retorna None si no hay token (para permitir vistas públicas).
        Levanta AuthenticationFailed si el token es inválido.
        """
        auth_header = request.META.get('HTTP_AUTHORIZATION', '').split()
        
        # Si no hay header Authorization, retorna None (para permitir vistas públicas)
        if not auth_header or len(auth_header) != 2 or auth_header[0] != 'Bearer':
            return None
        
        token = auth_header[1]
        
        try:
            #  Verificar token con Firebase
            decoded_token = auth.verify_id_token(token)
            
            uid = decoded_token.get('uid')
            email = decoded_token.get('email', f'{uid}@firebase.com')
            name = decoded_token.get('name', 'User')
            
            #  CREAR O OBTENER USUARIO EN DJANGO
            user, created = User.objects.get_or_create(
                firebase_uid=uid,
                defaults={
                    'email': email,
                    'first_name': name.split()[0] if name and name.strip() else 'User',
                    'last_name': ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else '',
                    'role': User.Roles.REGULAR,  # Rol por defecto
                    'is_active': True,
                    'is_staff': False,  #  SEGURIDAD: nunca crear staff automáticamente
                    'is_superuser': False,  #  SEGURIDAD: nunca crear superuser automáticamente
                }
            )
            
            if created:
                logger.info(f" Nuevo usuario creado en Django: {email} (UID: {uid})")
                print(f" Nuevo usuario creado: {email}")
            else:
                logger.info(f" Usuario encontrado en Django: {email}")
                print(f" Usuario encontrado: {email}")
            
            return (user, None)
        
        except auth.ExpiredIdTokenError:
            logger.warning(f"Expired Firebase token attempted")
            raise AuthenticationFailed('Token expirado')
        
        except auth.RevokedIdTokenError:
            logger.warning(f"Revoked Firebase token attempted")
            raise AuthenticationFailed('Token revocado')
        
        except auth.InvalidIdTokenError as e:
            logger.warning(f"Invalid Firebase token: {str(e)}")
            raise AuthenticationFailed('Token inválido')
        
        except Exception as e:
            logger.error(f"Error en autenticación Firebase: {str(e)}")
            raise AuthenticationFailed(f'Error de autenticación: {str(e)}')