#!/bin/sh
# Recovery after an updater boot failure; never restores or deletes the database.
set -eu
umask 022
cd /opt/aborigen-crm
if [ "$(id -u)" != 0 ]; then echo 'Run as root'; exit 1; fi
if systemctl is-active --quiet aborigen-crm-update.service; then
    echo 'Update worker is still active. Inspect its log before repair.'
    exit 1
fi
systemctl stop aborigen-crm-update.path
systemctl stop aborigen-crm-cleanup.timer aborigen-crm-cleanup.service aborigen-crm
bash deploy/install-service.sh
python3 - <<'PY'
import grp,json,os,subprocess,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
folder=Path('/var/lib/aborigen-crm-updater')
healthy=False
for _ in range(30):
    try:
        req=urllib.request.Request('http://127.0.0.1:8000/health/',headers={'Host':'crm.aborigen-tour.ru','X-Forwarded-Proto':'https'})
        with urllib.request.urlopen(req,timeout=3) as response:
            healthy=response.status==200 and response.read(64)==b'ok'
        if healthy:break
    except (OSError,ValueError):pass
    time.sleep(1)
if not healthy:
    subprocess.run(['journalctl','-u','aborigen-crm','-n','60','--no-pager'])
    raise SystemExit('CRM did not start. Maintenance marker preserved; database was not restored.')
try:data=json.loads((folder/'status.json').read_text())
except (OSError,ValueError):data={}
data.update(state='success',message='CRM восстановлена. Исправление прав доступа установлено.',recovery_failed=False,finished=datetime.now(timezone.utc).isoformat(),revision=subprocess.check_output(['git','rev-parse','--short=12','HEAD']).decode().strip())
temp=folder/'status.tmp';temp.write_text(json.dumps(data,ensure_ascii=False));temp.chmod(0o640);os.chown(temp,0,grp.getgrnam('aborigen-crm').gr_gid);temp.replace(folder/'status.json')
with (folder/'latest.log').open('ab') as log:log.write(b'\nManual repair completed: tracked code permissions fixed; service-account check and health check passed.\n')
(folder/'maintenance').unlink(missing_ok=True)
print('CRM recovered; maintenance disabled after successful health check.')
PY
