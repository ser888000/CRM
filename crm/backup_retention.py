"""Standard-library-only retention for owned, completed SQLite backup files."""
import re
import sqlite3
from pathlib import Path

ROOT_PATTERN = re.compile(r'(?:before-web-update-\d{8}-\d{6}-[0-9a-f]{8}|\d{8}-\d{6})\.sqlite3')
PASSPORT_PATTERN = re.compile(r'[0-9a-f]{32}\.sqlite3')


def valid_database(path):
    try:
        if Path(path).stat().st_size == 0:
            return False
        with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
            return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()) and db.execute('PRAGMA quick_check').fetchall() == [('ok',)]
    except (OSError, sqlite3.Error):
        return False


def prune_backups(folder, pattern, protected=(), glob_pattern='*.sqlite3'):
    """Keep newest file AND newest verified backup; never follow symlinks.

    Run before creating the next backup. If no copy verifies, delete nothing.
    Callers must serialize this operation with backup creation.
    """
    folder = Path(folder)
    files = sorted((p for p in folder.glob(glob_pattern)
                    if pattern.fullmatch(p.name) and not p.is_symlink() and p.is_file()),
                   key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    if not files:
        return 0
    verified = next((p for p in files if valid_database(p)), None)
    if verified is None:
        return 0
    keep = {files[0], verified, *(Path(p) for p in protected)}
    freed = 0
    for path in files:
        if path not in keep:
            size = path.stat().st_size
            path.unlink()
            freed += size
    return freed
