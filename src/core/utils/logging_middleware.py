import logging
import time
import json

logger = logging.getLogger('django.request')

class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        start_time = time.time()

        response = self.get_response(request)
        duration = time.time() - start_time

        ip = self.get_client_ip(request)
        
        #  FIX: Verifica si user tiene is_authenticated
        if hasattr(request, 'user') and hasattr(request.user, 'is_authenticated'):
            user = request.user.id if request.user.is_authenticated else 'Anonymous'
        else:
            user = 'Anonymous'
        
        status_code = response.status_code

        log_data = {
            "method": request.method,
            "path": request.path,
            "status": status_code,
            "duration": round(duration, 4),
            "ip": ip,
            "user_id": user
        }

        if status_code >= 500:
            logger.error(f"SERVER ERROR: {json.dumps(log_data)}")
        elif status_code >= 400:
            logger.warning(f"CLIENT ERROR: {json.dumps(log_data)}")
        else:
            logger.info(f"SUCCESS: {json.dumps(log_data)}")
        
        return response
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip