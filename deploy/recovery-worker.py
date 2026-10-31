#!/usr/bin/python3
"""Privileged systemd worker: only fixed database/full requests are accepted."""
import fcntl
import grp
import json
import os
import stat
import sys
import tempfile
import uuid
from pathlib import Path

from crm_recovery import (STATE, REQUEST, DATABASE, build_bundle, digest,
                          restic_environment, snapshot, stamp, upload_verified)


def publish(name, data):
    temporary = STATE / (name + '.pending')
    temporary.write_text(json.dumps(data, ensure_ascii=False))
    os.chown(temporary, 0, grp.getgrnam('aborigen-crm').gr_gid)
    temporary.chmod(0o640)
    temporary.replace(STATE / name)


def read_request():
    fd = os.open(REQUEST, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024:
            raise ValueError('Invalid request file')
        data = json.load(stream)
    if data.get('kind') not in ('database', 'full') or str(uuid.UUID(data['request_id'])) != data['request_id']:
        raise ValueError('Invalid request')
    return {'kind': data['kind'], 'request_id': data['request_id']}


def main(mode):
    if os.geteuid() != 0 or mode not in ('manual', 'daily'):
        raise SystemExit('Run as root: manual or daily')
    os.umask(0o077)
    state_name = 'status.json' if mode == 'manual' else 'remote.json'
    data = {'state': 'running', 'started': stamp(), 'message': 'Создаётся резервная копия.'}
    last_success = {}
    try:
        last_success = json.loads((STATE / state_name).read_text()).get('last_success', {})
    except (OSError, ValueError):
        pass
    with open('/run/aborigen-crm-recovery.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            if mode == 'manual':
                data.update(read_request())
            publish(state_name, {**data, 'last_success': last_success})
            if mode == 'manual':
                REQUEST.unlink(missing_ok=True)
            environment = restic_environment() if mode == 'daily' else None
            # Serialize snapshots/code archiving with updater and cleanup.
            with tempfile.TemporaryDirectory(prefix='.job-', dir=STATE) as work:
                extension = '.sqlite3' if data.get('kind') == 'database' else '.tar.gz'
                bundle = Path(work) / ('backup' + extension)
                with open('/run/aborigen-crm-update.lock', 'a') as update_lock:
                    fcntl.flock(update_lock, fcntl.LOCK_EX)
                    if Path('/var/lib/aborigen-crm-updater/maintenance').exists():
                        raise ValueError('Recovery of a failed update is pending')
                    if data.get('kind') == 'database':
                        snapshot(DATABASE, bundle)
                    else:
                        build_bundle(bundle)
                checksum = digest(bundle)
                if mode == 'daily':
                    snapshot_id = upload_verified(bundle, environment)
                    last_success = {'finished': stamp(), 'snapshot': snapshot_id, 'sha256': checksum, 'bytes': bundle.stat().st_size}
                else:
                    target = STATE / 'downloads' / (data['request_id'] + extension)
                    size = bundle.stat().st_size
                    os.chown(bundle, 0, grp.getgrnam('aborigen-crm').gr_gid)
                    bundle.chmod(0o640)
                    bundle.replace(target)
                    data.update(filename=target.name, bytes=size, sha256=checksum)
                    last_success = {**data, 'finished': stamp()}
                    # Keep one completed manual download, never delete it before a new success.
                    for old in target.parent.iterdir():
                        if old != target and old.is_file() and not old.is_symlink():
                            old.unlink()
                data.update(state='ready', finished=stamp(), message='Копия создана и проверена.' if mode == 'manual' else 'Внешняя копия загружена и проверена.')
                publish(state_name, {**data, 'last_success': last_success})
                print(data['message'])
        except Exception:
            if mode == 'manual':
                REQUEST.unlink(missing_ok=True)
            publish(state_name, {**data, 'state': 'failed', 'finished': stamp(), 'last_success': last_success,
                                 'message': 'Не удалось создать или проверить копию. Проверьте свободное место и настройки службы; предыдущая копия сохранена.'})
            # Exception text may contain paths, S3 credentials or application data.
            print('CRM backup failed; no secrets or personal data logged.', file=sys.stderr)
            raise SystemExit(1)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) == 2 else '')
