"""The web app can request a fixed updater; it never runs privileged commands."""
import json
import os
import re
import uuid
import tempfile
from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .models import AuditEvent


def paths():
    return (Path(getattr(settings,'CRM_UPDATE_REQUEST','/var/lib/aborigen-crm/update-request.json')),
            Path(getattr(settings,'CRM_UPDATE_STATE','/var/lib/aborigen-crm-updater')))


def require_admin(user):
    if not user.is_active or not user.is_superuser:raise PermissionDenied


def state():
    request_path,folder=paths()
    result={'state':'idle','message':'Можно установить последнюю опубликованную версию.','ready':(folder/'installed').is_file()}
    try:
        data=json.loads((folder/'status.json').read_text())
        result.update({key:data[key] for key in ('state','message','started','finished','old_revision','revision','backup','request_id','recovery_failed') if key in data})
    except (OSError,ValueError,TypeError):pass
    if request_path.exists():
        try:pending=json.loads(request_path.read_text())
        except (OSError,ValueError):pending={}
        if result.get('request_id')!=pending.get('request_id') or result['state'] not in ('running',):
            result.update(state='queued',message='Запрос принят. Ожидаем запуска службы обновления.')
    result['blocked']=bool(result.get('recovery_failed'))
    result['busy']=result['state'] in ('queued','running')
    return result


def log_tail():
    _,folder=paths()
    try:
        with (folder/'latest.log').open('rb') as log:
            log.seek(0,2);log.seek(max(0,log.tell()-24000));text=log.read().decode('utf-8',errors='replace')
    except OSError:return ''
    text=re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@',r'\1[скрыто]@',text)
    return re.sub(r'(?i)((?:authkey|api_key|password|secret|token)=)[^\s&]+',r'\1[скрыто]',text)

@login_required
@never_cache
def page(request):
    require_admin(request.user)
    return render(request,'crm/update.html',{'update':state()})

@login_required
@never_cache
def status(request):
    require_admin(request.user)
    return JsonResponse({**state(),'log':log_tail()})

@login_required
@require_POST
@never_cache
def start(request):
    require_admin(request.user)
    from .legacy_history_jobs import state as history_state
    if history_state().get('state') in ('queued','running'):return JsonResponse({'error':'Сначала дождитесь окончания переноса старой CRM.'},status=409)
    request_path,folder=paths()
    if not (folder/'installed').is_file():return JsonResponse({'error':'Служба обновления ещё не установлена. Выполните первоначальную установку на VPS.'},status=503)
    if state()['busy']:return redirect('update_page')
    payload={'request_id':str(uuid.uuid4()),'actor_id':request.user.pk,'requested':timezone.now().isoformat()}
    if state().get('blocked'):return JsonResponse({'error':'Сначала требуется диагностика неудачного восстановления.'},status=503)
    # Publish a completely written file atomically; the root watcher never sees half a JSON.
    temporary=None
    try:
        fd,temporary=tempfile.mkstemp(prefix='.update-',dir=request_path.parent)
        with os.fdopen(fd,'w') as stream:
            json.dump(payload,stream);stream.flush();os.fsync(stream.fileno())
        os.link(temporary,request_path)
    except FileExistsError:return redirect('update_page')
    except OSError:return JsonResponse({'error':'Не удалось передать запрос службе обновления.'},status=503)
    finally:
        if temporary:Path(temporary).unlink(missing_ok=True)
    AuditEvent.objects.create(actor=request.user,object_type='system.Update',object_id=payload['request_id'],action='requested')
    return redirect('update_page')


def health(request):
    from django.db import connection
    from django.http import HttpResponse
    try:
        with connection.cursor() as cursor:cursor.execute('SELECT 1');cursor.fetchone()
    except Exception:return HttpResponse('unavailable',status=503,content_type='text/plain')
    return HttpResponse('ok',content_type='text/plain')
