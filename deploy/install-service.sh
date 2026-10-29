#!/bin/sh
# Run as root on the dedicated VPS after stopping runserver.
set -eu
umask 022
cd /opt/aborigen-crm
if [ "$(id -u)" != 0 ]; then echo 'Run as root'; exit 1; fi
if ! id aborigen-crm >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/aborigen-crm --shell /usr/sbin/nologin aborigen-crm
fi
python3 deploy/repair-code-permissions.py
.venv/bin/pip install --disable-pip-version-check -r requirements.txt
if systemctl is-active --quiet aborigen-crm; then systemctl stop aborigen-crm; fi
install -d -m 700 -o aborigen-crm -g aborigen-crm /var/lib/aborigen-crm
python3 - <<'PY'
import os,secrets,shlex,subprocess,sqlite3
from datetime import datetime
from pathlib import Path
from crm.backup_retention import prune_backups,ROOT_PATTERN,valid_database
p=Path('/etc/aborigen-crm.env')
if not p.exists():
    p.write_text('DJANGO_SETTINGS_MODULE=config.ssh_settings\nDJANGO_DEBUG=0\nDJANGO_COOKIE_SECURE=0\nDJANGO_ALLOWED_HOSTS=127.0.0.1,localhost\nCRM_DATABASE_PATH=/var/lib/aborigen-crm/db.sqlite3\nDJANGO_SECRET_KEY='+secrets.token_urlsafe(64)+'\n')
    p.chmod(0o600)
env=os.environ.copy()
for line in p.read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):continue
    key,value=line.split('=',1)
    parts=shlex.split(value)
    env[key]=parts[0] if parts else ''
if env.get('CRM_DATABASE_PATH')!='/var/lib/aborigen-crm/db.sqlite3':
    raise SystemExit('Unexpected database path in /etc/aborigen-crm.env; inspect before proceeding')
dest=Path(env['CRM_DATABASE_PATH'])
if not dest.exists() and Path('db.sqlite3').exists():
    with sqlite3.connect('db.sqlite3') as source,sqlite3.connect(dest) as backup:source.backup(backup)
if dest.exists():
    backup_dir=Path('/root/crm-backups');backup_dir.mkdir(mode=0o700,exist_ok=True)
    existing=os.environ.get('CRM_UPDATE_BACKUP')
    if existing:
        saved=Path(existing)
        if saved.parent!=backup_dir or not saved.is_file() or saved.is_symlink() or not valid_database(saved):
            raise SystemExit('Updater backup is unavailable or invalid; installation stopped')
    else:
        prune_backups(backup_dir,ROOT_PATTERN)
        target=backup_dir/(datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
        pending=target.with_suffix('.pending')
        try:
            with sqlite3.connect(dest) as source,sqlite3.connect(pending) as backup:source.backup(backup)
            if not valid_database(pending):raise SystemExit('Backup check failed')
            pending.chmod(0o600);pending.replace(target)
        finally:pending.unlink(missing_ok=True)
for args in [('migrate',),('seed_templates',),('collectstatic','--noinput'),('check',)]:
    subprocess.run(['.venv/bin/python','manage.py',*args],env=env,check=True)
PY
chown -R aborigen-crm:aborigen-crm /var/lib/aborigen-crm
# Root checks cannot detect code unreadable by the actual application account.
python3 - <<'PY_RUNTIME'
import os,pwd,shlex,subprocess
from pathlib import Path
runtime_env=os.environ.copy()
for line in Path('/etc/aborigen-crm.env').read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):continue
    key,value=line.split('=',1);parts=shlex.split(value);runtime_env[key]=parts[0] if parts else ''
runtime_env['PYTHONDONTWRITEBYTECODE']='1'
account=pwd.getpwnam('aborigen-crm')
subprocess.run(['.venv/bin/python','manage.py','check'],env=runtime_env,user=account.pw_uid,group=account.pw_gid,extra_groups=[],check=True)
PY_RUNTIME
install -m 644 deploy/aborigen-crm.service /etc/systemd/system/aborigen-crm.service
install -m 644 deploy/aborigen-crm-cleanup.service /etc/systemd/system/aborigen-crm-cleanup.service
install -m 644 deploy/aborigen-crm-cleanup.timer /etc/systemd/system/aborigen-crm-cleanup.timer
install -d -m 750 -o root -g aborigen-crm /var/lib/aborigen-crm-updater
install -d -m 755 -o root -g root /usr/local/libexec
install -m 644 -o root -g root crm/backup_retention.py /usr/local/libexec/crm_backup_retention.py
install -m 755 -o root -g root deploy/run-update.py /usr/local/libexec/aborigen-crm-update.py
install -m 755 -o root -g root deploy/repair-code-permissions.py /usr/local/libexec/aborigen-crm-code-permissions.py
install -m 644 deploy/aborigen-crm-update.path /etc/systemd/system/aborigen-crm-update.path
install -m 644 deploy/aborigen-crm-update.service /etc/systemd/system/aborigen-crm-update.service
systemctl daemon-reload
systemctl enable aborigen-crm-update.path
if ! systemctl is-active --quiet aborigen-crm-update.path; then systemctl start --no-block aborigen-crm-update.path; fi
install -m 640 -o root -g aborigen-crm /dev/null /var/lib/aborigen-crm-updater/installed
systemctl enable --now aborigen-crm-cleanup.timer
systemctl enable --now aborigen-crm
systemctl restart aborigen-crm
systemctl status aborigen-crm --no-pager
