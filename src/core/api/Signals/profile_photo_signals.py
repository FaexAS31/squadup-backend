"""
Signal to clean up Firebase Storage blobs when ProfilePhotos are deleted.
"""

import logging
from urllib.parse import unquote
from django.db.models.signals import post_delete
from django.dispatch import receiver
from api.models import ProfilePhoto

logger = logging.getLogger('api')


def _extract_storage_path(url):
    """Extract the Firebase Storage path from a download URL."""
    if not url:
        return None
    try:
        # Firebase URLs contain the path encoded between /o/ and ?
        if '/o/' in url:
            path_encoded = url.split('/o/')[1].split('?')[0]
            return unquote(path_encoded)
    except (IndexError, ValueError):
        pass
    return None


@receiver(post_delete, sender=ProfilePhoto)
def cleanup_firebase_storage(sender, instance, **kwargs):
    """Delete the Firebase Storage blob when a ProfilePhoto is deleted."""
    path = _extract_storage_path(instance.image_url)
    if not path:
        return

    try:
        import firebase_admin
        from firebase_admin import storage as fb_storage

        # Get or initialize default app
        try:
            app = firebase_admin.get_app()
        except ValueError:
            return  # Firebase not initialized

        bucket = fb_storage.bucket(app=app)
        blob = bucket.blob(path)
        if blob.exists():
            blob.delete()
            logger.info(f"Deleted Firebase blob: {path}")
    except Exception as e:
        logger.warning(f"Failed to delete Firebase blob {path}: {e}")
