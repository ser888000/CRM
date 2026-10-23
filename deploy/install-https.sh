#!/bin/bash
# Dedicated CRM VPS only. Existing CRM data and secrets are preserved.
set -euo pipefail
cd /opt/aborigen-crm
if [ "$(id -u)" != 0 ]; then echo 'Запустите от root'; exit 1; fi
if [ ! -f /etc/aborigen-crm.env ]; then echo 'Сначала выполните deploy/install-service.sh'; exit 1; fi
python3 - <<'PY'
import socket
addresses={entry[4][0] for entry in socket.getaddrinfo('crm.aborigen-tour.ru',80,type=socket.SOCK_STREAM)}
if addresses != {'168.113.171.231'}:
    raise SystemExit('DNS ещё не готов или есть лишняя A/AAAA запись: '+str(addresses))
print('DNS готов: crm.aborigen-tour.ru → 168.113.171.231')
PY
# Do not take ports away from an existing web server.
if [ ! -f /etc/caddy/aborigen-crm.Caddyfile ] && ss -ltnH '( sport = :80 or sport = :443 )' | read -r _; then
    echo 'Порты 80/443 уже заняты. Пришлите вывод: ss -ltnp'; exit 1
fi
apt-get update
apt-get install -y caddy
install -d /etc/caddy /etc/systemd/system/caddy.service.d
cat > /etc/caddy/aborigen-crm.Caddyfile <<'CADDY'
crm.aborigen-tour.ru {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
CADDY
cat > /etc/systemd/system/caddy.service.d/aborigen-crm.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/usr/bin/caddy run --environ --config /etc/caddy/aborigen-crm.Caddyfile
ExecReload=
ExecReload=/usr/bin/caddy reload --config /etc/caddy/aborigen-crm.Caddyfile --force
UNIT
caddy validate --config /etc/caddy/aborigen-crm.Caddyfile --adapter caddyfile
python3 - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil
p=Path('/etc/aborigen-crm.env')
shutil.copy2(p,Path('/root')/('crm-env-before-https-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
updates={'DJANGO_SETTINGS_MODULE':'config.public_settings','DJANGO_DEBUG':'0','DJANGO_COOKIE_SECURE':'1','DJANGO_ALLOWED_HOSTS':'crm.aborigen-tour.ru,127.0.0.1,localhost'}
lines=[]
for line in p.read_text().splitlines():
    key=line.split('=',1)[0]
    if key in updates:lines.append(key+'='+updates.pop(key))
    else:lines.append(line)
lines.extend(key+'='+value for key,value in updates.items())
p.write_text('\n'.join(lines)+'\n');p.chmod(0o600)
PY
# Only adjust UFW when it is already active; preserve existing SSH rules.
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow 80/tcp
    ufw allow 443/tcp
fi
systemctl daemon-reload
systemctl restart aborigen-crm
systemctl enable caddy
systemctl restart caddy
systemctl --no-pager --full status aborigen-crm caddy
printf '\nОткройте https://crm.aborigen-tour.ru — выпуск сертификата может занять несколько минут.\n'
