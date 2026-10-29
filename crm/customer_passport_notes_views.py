"""Admin-only, explicit execution with a verified SQLite backup before writes."""
import os
import sqlite3
import uuid
from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction, DatabaseError
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from .customer_passport_notes import plan
from .models import Customer, AuditEvent
from .update_views import require_admin


def backup_folder():
    return Path(settings.DATABASES['default']['NAME']).resolve().parent / 'customer-passport-backups'


class BackupError(ValueError):
    pass


def failure_message(error, stage):
    """Only known codes, never exception text (it may contain personal data/SQL)."""
    if isinstance(error, PermissionError):
        detail = 'Нет прав на чтение базы или запись резервной копии.'
    elif isinstance(error, OSError) and error.errno == 28:
        detail = 'На диске недостаточно свободного места.'
    elif isinstance(error, BackupError):
        detail = str(error)  # Our own fixed messages only.
    else:
        original = error.__cause__ or error
        code = getattr(original, 'sqlite_errorname', '')
        if code == 'SQLITE_BUSY' or code == 'SQLITE_LOCKED':
            detail = 'База занята другим процессом. Повторите после завершения других операций.'
        elif code == 'SQLITE_READONLY':
            detail = 'База или каталог копии доступны только для чтения.'
        else:
            detail = 'Код: ' + type(error).__name__ + ((' / ' + code) if code else '')
            if isinstance(error, OSError) and error.errno is not None:
                detail += ' / errno=' + str(error.errno)
    return f'{stage}: {detail} Изменения не применены.'


def backup():
    if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
        raise BackupError('Для этой базы требуется отдельный способ резервного копирования. Изменений нет.')
    folder = backup_folder()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / (uuid.uuid4().hex + '.sqlite3')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    database = Path(settings.DATABASES['default']['NAME']).resolve()
    try:
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(path) as target:
            source.backup(target)
            if target.execute('PRAGMA quick_check').fetchone() != ('ok',):
                raise BackupError('Резервная копия не прошла проверку. Изменений нет.')
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def page(request):
    require_admin(request.user)
    result = None
    error = ''
    backup_token = ''
    stage = 'Создание и проверка резервной копии'
    if request.method == 'POST':
        try:
            path = backup()  # Must succeed before the first update.
            backup_token = signing.dumps(path.name, salt='customer-passport-backup')
            stage = 'Заполнение паспортных полей'
            result = {'changed': 0, 'fields': 0, 'unchanged': 0, 'review': [],
                      'backup': backup_token}
            with transaction.atomic():
                for customer in Customer.objects.select_for_update().order_by('pk').iterator():
                    updates, reason = plan(customer)
                    if reason:
                        result['review'].append({'pk': customer.pk, 'name': customer.name, 'reason': reason})
                    elif updates:
                        # Avoid Customer.save() renormalizing unrelated name fields.
                        Customer.objects.filter(pk=customer.pk).update(**updates)
                        AuditEvent.objects.create(actor=request.user, object_type='Customer', object_id=str(customer.pk),
                            action='passport_from_notes', changes={'fields': sorted(updates), 'source': 'Примечание'})
                        result['changed'] += 1
                        result['fields'] += len(updates)
                    else:
                        result['unchanged'] += 1
        except (OSError, sqlite3.Error, DatabaseError, ValueError) as exc:
            result = None
            error = failure_message(exc, stage)
    return render(request, 'crm/customer_passport_notes.html', {'result': result, 'error': error, 'backup_token': backup_token})


@login_required
@never_cache
@require_GET
def download(request, token):
    require_admin(request.user)
    try:
        filename = signing.loads(token, salt='customer-passport-backup')
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.sqlite3'):
            raise ValueError
        return FileResponse((backup_folder() / filename).open('rb'), as_attachment=True,
                            filename='crm-before-passport-import.sqlite3')
    except (signing.BadSignature, OSError, ValueError):
        raise Http404
