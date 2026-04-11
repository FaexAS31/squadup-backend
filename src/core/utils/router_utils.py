import os
import importlib
from rest_framework.routers import SimpleRouter


def pluralize(word: str) -> str:
    """
    Pluraliza una palabra en inglés para URLs de API REST.

    Reglas:
    - Palabras que terminan en 'z' → agregar 'es' (blitz → blitzes)
    - Palabras que terminan en 'y' precedida de consonante → cambiar 'y' por 'ies'
    - Palabras que terminan en 's', 'x', 'sh', 'ch' → agregar 'es'
    - Todo lo demás → agregar 's'
    """
    word = word.lower()

    if word.endswith('z'):
        return word + 'es'
    elif word.endswith('y') and len(word) > 1 and word[-2] not in 'aeiou':
        return word[:-1] + 'ies'
    elif word.endswith(('s', 'x', 'sh', 'ch')):
        return word + 'es'
    else:
        return word + 's'


def register_all_viewsets(router, viewsets_module):
    """
    Auto-registra todos los ViewSets en la carpeta Viewsets/.

    Busca archivos *_viewset.py y registra cada ViewSet automáticamente.
    Los endpoints se pluralizan automáticamente (User → /users/, Blitz → /blitzes/).
    """
    viewsets_path = os.path.dirname(viewsets_module.__file__)

    for filename in os.listdir(viewsets_path):
        if filename.endswith('_viewset.py') and filename != '__init__.py':
            # Extraer nombre del módulo
            module_name = filename[:-3]  # Quitar .py

            try:
                # Importar dinámicamente
                module = importlib.import_module(f'api.Viewsets.{module_name}')

                # Buscar clases que terminen con 'ViewSet'
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)

                    # Verificar si es una clase y es ViewSet
                    if (isinstance(attr, type) and
                        attr_name.endswith('ViewSet') and
                        hasattr(attr, 'queryset')):

                        # Registrar automáticamente con nombre pluralizado
                        # basename = nombre del modelo (ej: User, Group, Blitz)
                        basename = attr_name.replace('ViewSet', '').lower()
                        plural_name = pluralize(basename)
                        router.register(plural_name, attr, basename=basename)

                        print(f" Registrado: {attr_name} → /{plural_name}/")

            except Exception as e:
                print(f"⚠️ Error registrando {module_name}: {str(e)}")

    return router