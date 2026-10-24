#!/bin/sh
# Run as root on the dedicated VPS after stopping runserver.
set -eu
cd /opt/aborigen-crm
if [ "$(id -u)" != 0 ]; then echo 'Run as root'; exit 1; fi
if ! id aborigen-crm >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/aborigen-crm --shell /usr/sbin/nologin aborigen-crm
fi
.venv/bin/pip install -r requirements.txt
if systemctl is-active --quiet aborigen-crm; then systemctl stop aborigen-crm; fi
install -d -m 700 -o aborigen-crm -g aborigen-crm /var/lib/aborigen-crm
python3 - <<'PY'
import os,secrets,shlex,subprocess,sqlite3
from datetime import datetime
from pathlib import Path
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
    with sqlite3.connect(dest) as source,sqlite3.connect(backup_dir/(datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')) as backup:source.backup(backup)
for args in [('migrate',),('seed_templates',),('collectstatic','--noinput'),('check',)]:
    subprocess.run(['.venv/bin/python','manage.py',*args],env=env,check=True)
PY
chown -R aborigen-crm:aborigen-crm /var/lib/aborigen-crm
install -m 644 deploy/aborigen-crm.service /etc/systemd/system/aborigen-crm.service
install -m 644 deploy/aborigen-crm-cleanup.service /etc/systemd/system/aborigen-crm-cleanup.service
install -m 644 deploy/aborigen-crm-cleanup.timer /etc/systemd/system/aborigen-crm-cleanup.timer
systemctl daemon-reload
systemctl enable --now aborigen-crm-cleanup.timer
systemctl enable --now aborigen-crm
systemctl restart aborigen-crm
systemctl status aborigen-crm --no-pager
