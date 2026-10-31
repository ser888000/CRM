#!/bin/sh
# Install fixed root-owned worker; S3 remains off until configured and tested.
set -eu
cd /opt/aborigen-crm
install -d -m 750 -o root -g aborigen-crm /var/lib/aborigen-crm-recovery
install -d -m 750 -o root -g aborigen-crm /var/lib/aborigen-crm-recovery/downloads
install -m 644 -o root -g root crm/recovery.py /usr/local/libexec/crm_recovery.py
install -m 755 -o root -g root deploy/recovery-worker.py /usr/local/libexec/aborigen-crm-recovery.py
install -m 755 -o root -g root deploy/restore-recovery.py /usr/local/libexec/aborigen-crm-restore.py
install -m 755 -o root -g root deploy/enable-offsite-backup.py /usr/local/libexec/aborigen-crm-enable-offsite.py
for unit in aborigen-crm-recovery.path aborigen-crm-recovery.service aborigen-crm-offsite.service aborigen-crm-offsite.timer; do
    install -m 644 -o root -g root "deploy/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable aborigen-crm-recovery.path
systemctl start --no-block aborigen-crm-recovery.path
install -m 640 -o root -g aborigen-crm /dev/null /var/lib/aborigen-crm-recovery/installed
