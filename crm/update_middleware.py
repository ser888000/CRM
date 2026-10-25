from django.conf import settings
from django.http import HttpResponse
from pathlib import Path

class UpdateMaintenanceMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        folder=Path(getattr(settings,'CRM_UPDATE_STATE','/var/lib/aborigen-crm-updater'))
        if (folder/'maintenance').exists() and not (request.path.startswith('/management/update/') or request.path=='/health/'):
            return HttpResponse('CRM обновляется. Подождите и обновите страницу. Статус: /management/update/',status=503,headers={'Retry-After':'10'},content_type='text/plain; charset=utf-8')
        if request.method not in ('GET','HEAD','OPTIONS') and not request.path.startswith(('/management/legacy/','/management/update/','/admin/login/','/admin/logout/')):
            from .legacy_history_jobs import state
            if state().get('state') in ('queued','running'):
                return HttpResponse('Выполняется перенос старой CRM. Дождитесь завершения перед изменением данных.',status=503,headers={'Retry-After':'10'},content_type='text/plain; charset=utf-8')
        return self.get_response(request)
