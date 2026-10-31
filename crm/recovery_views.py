"""Superuser-only backup UI; no root commands or direct access to private settings."""
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .models import AuditEvent
from .update_views import require_admin


def paths():
    return (Path(getattr(settings, 'CRM_RECOVERY_REQUEST', '/var/lib/aborigen-crm/recovery-request.json')),
            Path(getattr(settings, 'CRM_RECOVERY_STATE', '/var/lib/aborigen-crm-recovery')))


def read_status(name):
    try:
        data = json.loads((paths()[1] / name).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def state():
    request_file, folder = paths()
    manual = read_status('status.json')
    manual['installed'] = (folder / 'installed').is_file()
    manual['busy'] = request_file.exists() or manual.get('state') == 'running'
    if manual.get('state') == 'running':
        try:
            expired = timezone.now() - datetime.fromisoformat(manual['started']) > timedelta(minutes=50)
        except (ValueError, KeyError, TypeError):
            expired = True
        if expired:
            manual.update(state='failed', busy=request_file.exists(), message='Служба не завершила копирование вовремя. Проверьте её состояние на сервере.')

    return {'manual': manual, 'remote': read_status('remote.json'),
            'scheduled': (folder / 'offsite-enabled').is_file()}


@login_required
@never_cache
def page(request):
    require_admin(request.user)
    return render(request, 'crm/recovery.html', state())


@login_required
@never_cache
def status(request):
    require_admin(request.user)
    return JsonResponse(state())


@login_required
@require_POST
@never_cache
def start(request):
    require_admin(request.user)
    kind = request.POST.get('kind')
    if kind not in ('database', 'full'):
        return JsonResponse({'error': 'Неизвестный вид копии.'}, status=400)
    current = state()
    if not current['manual']['installed']:
        return JsonResponse({'error': 'Служба резервного копирования не установлена.'}, status=503)
    if current['manual']['busy']:
        return redirect('recovery_page')
    request_path, _ = paths()
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.recovery-', dir=request_path.parent)
        payload = {'request_id': str(uuid.uuid4()), 'kind': kind, 'requested': timezone.now().isoformat()}
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, request_path)
    except FileExistsError:
        return redirect('recovery_page')
    except OSError:
        return JsonResponse({'error': 'Не удалось передать запрос службе.'}, status=503)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
    AuditEvent.objects.create(actor=request.user, object_type='system.Backup', object_id=payload['request_id'], action='requested')
    return redirect('recovery_page')


@login_required
@never_cache
def download(request, request_id):
    require_admin(request.user)
    current = read_status('status.json')
    data = current.get('last_success') or (current if current.get('state') == 'ready' else {})
    filename = data.get('filename', '')
    if data.get('request_id') != str(request_id) or not re.fullmatch(r'[0-9a-f-]{36}\.(?:sqlite3|tar\.gz)', filename) or not filename.startswith(str(request_id) + '.'):
        raise Http404
    path = paths()[1] / 'downloads' / filename
    if path.is_symlink() or not path.is_file():
        raise Http404
    response = FileResponse(path.open('rb'), as_attachment=True, filename='crm-' + filename, content_type='application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Referrer-Policy'] = 'no-referrer'
    AuditEvent.objects.create(actor=request.user, object_type='system.Backup', object_id=str(request_id), action='downloaded')
    return response
