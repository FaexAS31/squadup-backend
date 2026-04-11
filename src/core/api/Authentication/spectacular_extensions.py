from drf_spectacular.extensions import OpenApiAuthenticationExtension
from api.Authentication.authentication import FirebaseAuthentication


class FirebaseAuthenticationExtension(OpenApiAuthenticationExtension):
    """
    🔑 Extensión de drf-spectacular para documentar FirebaseAuthentication en Swagger.
    """
    target_class = FirebaseAuthentication
    name = 'FirebaseAuth'
    
    #  CAMBIO: get_security_definition (no get_security_scheme)
    def get_security_definition(self, auto_schema):
        """Define cómo se ve la autenticación en OpenAPI."""
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': 'Firebase ID Token. Format: "Bearer {token}"',
        }