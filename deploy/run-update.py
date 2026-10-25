#!/usr/bin/python3
"""Root-owned, fixed-purpose systemd worker. No commands/paths come from HTTP."""
import fcntl
import json
import os
import pwd
import shlex
import shutil
import signal
import sqlite3
import stat
import subprocess
import time
import tempfile
import urllib.request
import uuid
from datetime import datetime,timezone
from pathlib import Path

REPO=Path('/opt/aborigen-crm')
REQUEST=Path('/var/lib/aborigen-crm/update-request.json')
STATE=Path('/var/lib/aborigen-crm-updater')
DB=Path('/var/lib/aborigen-crm/db.sqlite3')
ENV=Path('/etc/aborigen-crm.env')
BACKUPS=Path('/root/crm-backups')
LOCK=Path('/run/aborigen-crm-update.lock')
ALLOWED_ORIGINS={'https://github.com/ser888000/CRM','https://github.com/ser888000/CRM.git'}


def stamp():return datetime.now(timezone.utc).isoformat()


def publish(data):
    temp=STATE/'status.tmp';temp.write_text(json.dumps(data,ensure_ascii=False));temp.chmod(0o640)
    os.chown(temp,0,pwd.getpwnam('aborigen-crm').pw_gid);temp.replace(STATE/'status.json')


def run(args,log,timeout=900):
    log.write(('> '+' '.join(str(v) for v in args)+'\n').encode());log.flush()
    process=subprocess.Popen(args,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:code=process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
        raise RuntimeError('Превышено время выполнения шага обновления.')
    if code:raise subprocess.CalledProcessError(code,args)


def git(*args):
    return subprocess.check_output(['git',*args],cwd=REPO,stderr=subprocess.STDOUT,timeout=120).decode().strip()


def healthy():
    # Same Django instance and database, without exposing any application data.
    for _ in range(45):
        try:
            req=urllib.request.Request('http://127.0.0.1:8000/health/',headers={'Host':'crm.aborigen-tour.ru','X-Forwarded-Proto':'https'})
            with urllib.request.urlopen(req,timeout=3) as response:
                if response.status==200 and response.read(64)==b'ok':return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise RuntimeError('CRM не прошла проверку после запуска.')


def validate_database():
    values={}
    for line in ENV.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,value=line.split('=',1);parts=shlex.split(value);values[key]=parts[0] if parts else ''
    if values.get('POSTGRES_HOST') or values.get('CRM_DATABASE_PATH')!=str(DB) or DB.is_symlink():
        raise RuntimeError('Настройки базы не соответствуют службе обновления SQLite. Нужна проверка конфигурации сервера.')


def backup_database(dest):
    with sqlite3.connect(f'file:{DB}?mode=ro',uri=True) as source,sqlite3.connect(dest) as backup:source.backup(backup)
    dest.chmod(0o600)


def restore_database(source):
    fd,name=tempfile.mkstemp(prefix='.restore-',dir=DB.parent)
    dest=Path(name)
    try:
        account=pwd.getpwnam('aborigen-crm')
        with os.fdopen(fd,'wb') as output,source.open('rb') as original:
            shutil.copyfileobj(original,output);output.flush();os.fsync(output.fileno())
            os.fchown(output.fileno(),account.pw_uid,account.pw_gid)
        for suffix in ('-wal','-shm','-journal'):Path(str(DB)+suffix).unlink(missing_ok=True)
        dest.replace(DB)
    finally:dest.unlink(missing_ok=True)


def read_request():
    fd=os.open(REQUEST,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>4096 or info.st_uid!=pwd.getpwnam('aborigen-crm').pw_uid:raise ValueError('Invalid update request')
        data=json.load(stream)
    if str(uuid.UUID(data['request_id']))!=data['request_id'] or type(data['actor_id']) is not int or data['actor_id']<1:raise ValueError('Invalid update request')
    return data


def main():
    os.umask(0o022)
    os.environ['GIT_TERMINAL_PROMPT']='0'
    os.environ['PIP_NO_INPUT']='1'
    os.environ['PIP_DISABLE_PIP_VERSION_CHECK']='1'
    os.environ['PIP_DEFAULT_TIMEOUT']='20'
    os.environ['PIP_RETRIES']='2'
    with open(LOCK,'w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        data={'state':'running','message':'Проверяем опубликованную версию.','started':stamp()}
        old=None;backup=None;stopped=False
        with (STATE/'latest.log').open('wb',buffering=0) as log:
            os.chown(STATE/'latest.log',0,pwd.getpwnam('aborigen-crm').pw_gid);os.chmod(STATE/'latest.log',0o640)
            try:
                request=read_request();data['request_id']=request['request_id'];publish(data)
                if (STATE/'maintenance').exists():
                    data['recovery_failed']=True
                    raise RuntimeError('Предыдущее обновление было прервано. Нужна диагностика сервера; режим обслуживания сохранён.')
                validate_database()
                if git('remote','get-url','origin') not in ALLOWED_ORIGINS:raise RuntimeError('Неожиданный адрес репозитория. Обновление остановлено.')
                if git('status','--porcelain'):raise RuntimeError('На сервере есть локальные изменения кода. Автоматическое обновление остановлено.')
                old=git('rev-parse','HEAD');data['old_revision']=old[:12]
                run(['git','fetch','origin','main'],log,180)
                target=git('rev-parse','refs/remotes/origin/main');data['revision']=target[:12]
                run(['git','merge-base','--is-ancestor',old,target],log,30)
                if old==target:
                    data.update(state='success',message='Уже установлена последняя версия.')
                else:
                    data['message']='Создаём резервную копию и устанавливаем обновление.';publish(data)
                    (STATE/'maintenance').touch(mode=0o640)
                    stopped=True;run(['systemctl','stop','aborigen-crm-cleanup.timer','aborigen-crm-cleanup.service','aborigen-crm'],log,90)
                    BACKUPS.mkdir(mode=0o700,parents=True,exist_ok=True)
                    candidate=BACKUPS/('before-web-update-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+request['request_id'][:8]+'.sqlite3')
                    backup_database(candidate);backup=candidate;data['backup']=backup.name;publish(data)
                    run(['git','merge','--ff-only',target],log,60)
                    run(['python3','/usr/local/libexec/aborigen-crm-code-permissions.py'],log,60)
                    run(['bash','deploy/install-service.sh'],log,1200)
                    healthy();data.update(state='success',message='Обновление установлено. CRM работает.')
            except Exception as exc:
                log.write((f'Update failed: {type(exc).__name__}\n').encode())
                data.update(state='failed',message=str(exc) if isinstance(exc,RuntimeError) else 'Не удалось установить обновление. Подробности в журнале.')
                if stopped and old:
                    data['message']='Ошибка установки. Восстанавливаем прежнюю версию и базу.';publish(data)
                    try:
                        run(['systemctl','stop','aborigen-crm-cleanup.timer','aborigen-crm-cleanup.service','aborigen-crm'],log,90)
                        run(['git','reset','--hard',old],log,60)
                        run(['python3','/usr/local/libexec/aborigen-crm-code-permissions.py'],log,60)
                        if backup:restore_database(backup)
                        run(['bash','deploy/install-service.sh'],log,1200)
                        healthy();data['revision']=old[:12];data['message']='Обновление не установлено. Прежняя версия и база восстановлены.'
                    except Exception:
                        log.write(b'Recovery failed. Manual server inspection is required.\n')
                        data['message']='Не удалось завершить восстановление. Нужна диагностика сервера.'+(' Резервная копия сохранена.' if backup else '')
                        # Keep maintenance mode: do not accept writes to an uncertain schema.
                        data['recovery_failed']=True
            finally:
                data['finished']=stamp();publish(data)
                if not data.get('recovery_failed'):(STATE/'maintenance').unlink(missing_ok=True)
                REQUEST.unlink(missing_ok=True)

if __name__=='__main__':main()
