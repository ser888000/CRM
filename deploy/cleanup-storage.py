#!/usr/bin/python3
"""Explicit cleanup: retain latest backups; remove completed legacy job files."""
import fcntl
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crm.backup_retention import prune_backups, ROOT_PATTERN, PASSPORT_PATTERN, valid_database


def cleanup_legacy(base):
    base = Path(base)
    if not base.exists():
        return 0
    freed = 0
    with (base / 'request.lock').open('a') as request_lock, (base / 'worker.lock').open('a') as worker_lock:
        owner = base.stat()
        if os.geteuid() == 0:
            os.fchown(request_lock.fileno(), owner.st_uid, owner.st_gid)
            os.fchown(worker_lock.fileno(), owner.st_uid, owner.st_gid)
        fcntl.flock(request_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(worker_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for job in base.iterdir():
            if not job.is_dir() or job.is_symlink():
                continue
            try:
                if str(uuid.UUID(job.name)) != job.name:
                    continue
                status = json.loads((job / 'status.json').read_text())
            except (ValueError, OSError):
                continue
            if status.get('state') not in ('completed', 'failed'):
                continue
            size = sum(p.stat().st_size for p in job.rglob('*') if p.is_file() and not p.is_symlink())
            shutil.rmtree(job)
            freed += size
    return freed


def main():
    if os.geteuid() != 0:
        raise SystemExit('Запустите под root.')
    with open('/run/aborigen-crm-update.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if Path('/var/lib/aborigen-crm-updater/maintenance').exists() or Path('/var/lib/aborigen-crm/update-request.json').exists():
            raise SystemExit('Есть незавершённое обновление. Очистка отменена.')
        root = Path('/root/crm-backups')
        if not any(valid_database(p) for p in root.glob('*.sqlite3') if ROOT_PATTERN.fullmatch(p.name) and not p.is_symlink()):
            raise SystemExit('Нет проверенной резервной копии. Очистка отменена.')
        freed = prune_backups(root, ROOT_PATTERN)
        passports = Path('/var/lib/aborigen-crm/customer-passport-backups')
        if passports.exists():
            with (passports / 'backup.lock').open('a') as passport_lock:
                owner = passports.stat()
                os.fchown(passport_lock.fileno(), owner.st_uid, owner.st_gid)
                fcntl.flock(passport_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                freed += prune_backups(passports, PASSPORT_PATTERN)
        freed += cleanup_legacy('/var/lib/aborigen-crm/legacy-imports')
        print(f'Освобождено: {freed / 1024**3:.2f} ГБ. Последние копии сохранены. Рабочая база не изменена.')


if __name__ == '__main__':
    main()
