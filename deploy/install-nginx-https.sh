#!/bin/bash
# Dedicated Ubuntu CRM VPS; preserve other Nginx sites.
set -euo pipefail
cd /opt/aborigen-crm
if [ "$(id -u)" != 0 ]; then echo 'Запустите от root'; exit 1; fi
if [ ! -f /etc/aborigen-crm.env ]; then echo 'Сначала выполните deploy/install-service.sh'; exit 1; fi
python3 - <<'PY'
import socket
addresses={entry[4][0] for entry in socket.getaddrinfo('crm.aborigen-tour.ru',80,type=socket.SOCK_STREAM)}
if addresses != {'168.113.171.231'}:raise SystemExit('Проверьте A/AAAA записи DNS: '+str(addresses))
print('DNS готов')
PY
apt-get update
apt-get install -y nginx certbot
install -d /var/www/letsencrypt /root/crm-backups
site=/etc/nginx/sites-available/aborigen-crm
if [ -e "$site" ]; then cp -p "$site" "/root/crm-backups/nginx-$(date +%Y%m%d-%H%M%S).conf"; fi
# Before obtaining the certificate expose only ACME challenges, never the login form.
if [ ! -f /etc/letsencrypt/live/crm.aborigen-tour.ru/fullchain.pem ]; then
cat > "$site" <<'NGINX'
server {
    listen 80;
    server_name crm.aborigen-tour.ru;
    location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 404; }
}
NGINX
ln -sfn "$site" /etc/nginx/sites-enabled/aborigen-crm
nginx -t
systemctl reload nginx
fi
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow 80/tcp
    ufw allow 443/tcp
fi
certbot certonly --webroot -w /var/www/letsencrypt -d crm.aborigen-tour.ru --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
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
cat > "$site" <<'NGINX'
server {
    listen 80;
    server_name crm.aborigen-tour.ru;
    location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
    location / { return 301 https://crm.aborigen-tour.ru$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name crm.aborigen-tour.ru;
    ssl_certificate /etc/letsencrypt/live/crm.aborigen-tour.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/crm.aborigen-tour.ru/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 10m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
NGINX
ln -sfn "$site" /etc/nginx/sites-enabled/aborigen-crm
nginx -t
install -d /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx <<'HOOK'
#!/bin/sh
/usr/sbin/nginx -t && /bin/systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
systemctl enable --now certbot.timer
systemctl restart aborigen-crm
systemctl reload nginx
curl --fail --silent --show-error -I https://crm.aborigen-tour.ru/admin/login/
printf '\nГотово: https://crm.aborigen-tour.ru\n'
