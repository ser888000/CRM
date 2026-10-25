"""App-user background import; fixed command, private files, SQLite backup, no shell."""
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from django.conf import settings
from django.utils import timezone


def folder(create=True):
    data_dir=Path(settings.DATABASES['default']['NAME']).resolve().parent
    default=(settings.BASE_DIR.parent/'legacy-import-jobs') if data_dir==settings.BASE_DIR else data_dir/'legacy-imports'
    base=Path(getattr(settings,'CRM_LEGACY_IMPORT_DIR',os.getenv('CRM_LEGACY_IMPORT_DIR',default)))
    if create:base.mkdir(mode=0o700,parents=True,exist_ok=True)
    return base


def job_folder(key):return folder()/str(uuid.UUID(str(key)))


def write_json(path,data):
    temp=path.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as output:json.dump(data,output,ensure_ascii=False)
    os.replace(temp,path)


def read_json(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def process_alive(pid,job):
    if type(pid) is not int or pid<1:return False
    try:
        os.kill(pid,0)
        proc=Path(f'/proc/{pid}')
        if (proc/'stat').exists():
            fields=(proc/'stat').read_text().rpartition(')')[2].split()
            if not fields or fields[0] in ('Z','X'):return False
            # Do not mistake a reused PID for our old worker.
            if ('\0'+job+'\0').encode() not in (proc/'cmdline').read_bytes():return False
        return True
    except OSError:return False


def state():
    key=read_json(folder(False)/'active.json').get('job')
    if not key:return {'state':'idle'}
    try:job=job_folder(key)
    except (ValueError,TypeError):return {'state':'failed','message':'Не удалось прочитать состояние загрузки.'}
    result=read_json(job/'status.json');meta=read_json(job/'meta.json')
    if result.get('state') in ('queued','running') and not process_alive(meta.get('pid'),key):
        result={'state':'failed','message':'Процесс загрузки прерван. Незавершённая транзакция отменяется автоматически. Повтор того же пакета безопасен.'}
    return {'job':key,**result}


def start_job(upload,actor,replace=False):
    if settings.DATABASES['default']['ENGINE']!='django.db.backends.sqlite3':raise ValueError('Для этого варианта загрузки требуется резервное копирование SQLite.')
    from .update_views import state as update_state
    if update_state().get('busy'):raise ValueError('Сначала дождитесь завершения обновления CRM.')
    base=folder()
    with (base/'request.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if state().get('state') in ('queued','running'):raise ValueError('Загрузка уже выполняется. Дождитесь результата.')
        key=str(uuid.uuid4());job=job_folder(key);job.mkdir(mode=0o700)
        write_json(job/'meta.json',{'actor_id':actor.pk,'replace':bool(replace)})
        fd=os.open(job/'package.zip',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as output:
            size=0
            for chunk in upload.chunks():
                size+=len(chunk)
                if size>8*1024*1024:raise ValueError('Пакет должен быть не больше 8 МБ.')
                output.write(chunk)
        write_json(job/'status.json',{'state':'queued','message':'Пакет принят. Проверяем данные.','started':timezone.now().isoformat()})
        # Do not write stdout/stderr: Django tracebacks can include personal values.
        try:
            process=subprocess.Popen([sys.executable,str(settings.BASE_DIR/'manage.py'),'import_legacy_history','--job',key],cwd=settings.BASE_DIR,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True,env={**os.environ,'CRM_DATABASE_PATH':str(settings.DATABASES['default']['NAME']),'CRM_LEGACY_IMPORT_DIR':str(base)})
        except OSError:
            (job/'package.zip').unlink(missing_ok=True);raise ValueError('Не удалось запустить загрузку.')
        write_json(job/'meta.json',{'actor_id':actor.pk,'pid':process.pid,'replace':bool(replace)})
        write_json(base/'active.json',{'job':key})
        return key


def run_job(key):
    from django.contrib.auth import get_user_model
    from django.db import connections
    from .legacy_history import load_history,prepare_history,apply_history,HistoryImportError
    settings.DEBUG=False
    job=job_folder(key)
    with (folder()/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            write_json(job/'status.json',{'state':'failed','message':'Другая загрузка ещё выполняется.'});return
        started=timezone.now().isoformat()
        def progress(message):write_json(job/'status.json',{'state':'running','message':message,'started':started})
        try:
            progress('Проверяем структуру, связи и суммы')
            with (job/'package.zip').open('rb') as file:data=load_history(file)
            meta=read_json(job/'meta.json')
            replace=meta.get('replace',False)
            if replace and data.get('format')!='aborigen-legacy-history-v2':raise HistoryImportError('Для очистки и повторной загрузки нужен новый пакет истории версии 2.')
            _,_,report=prepare_history(data)
            write_json(job/'preflight.json',report)
            progress('Сохраняем резервную копию базы перед загрузкой')
            connections.close_all()
            db=Path(settings.DATABASES['default']['NAME'])
            backup=job/'before.sqlite3'
            fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as src,sqlite3.connect(backup) as dest:src.backup(dest)
            actor=get_user_model().objects.get(pk=read_json(job/'meta.json')['actor_id'],is_active=True,is_superuser=True)
            from .legacy_reset import replace_history
            run,created=(replace_history if replace else apply_history)(data,actor,progress)
            write_json(job/'status.json',{'state':'completed','message':'Тренировочная история загружена.' if created else 'Этот снимок уже загружен. Дубликаты не созданы.','started':started,'finished':timezone.now().isoformat(),'run_id':run.pk,'report':run.summary})
        except HistoryImportError as error:
            write_json(job/'status.json',{'state':'failed','message':str(error),'started':started})
        except Exception:
            # Details may contain passports or raw SQL parameters; do not publish/log them.
            write_json(job/'status.json',{'state':'failed','message':'Загрузка не завершена. Изменения этой загрузки отменены. Требуется проверка пакета или состояния сервера.','started':started})
        finally:
            (job/'package.zip').unlink(missing_ok=True)
            connections.close_all()
