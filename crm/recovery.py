"""Fixed-purpose, root-run recovery backups. No paths or commands from HTTP."""
import hashlib
import json
import os
import configparser
import re
import shlex
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path('/opt/aborigen-crm')
DATABASE = Path('/var/lib/aborigen-crm/db.sqlite3')
ENV = Path('/etc/aborigen-crm.env')
STATE = Path('/var/lib/aborigen-crm-recovery')
REQUEST = Path('/var/lib/aborigen-crm/recovery-request.json')
FORMAT = 'aborigen-crm-recovery-v1'


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_database(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('Database verification failed')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            raise ValueError('Empty database')


def snapshot(source, target):
    source, target = Path(source), Path(target)
    if not source.is_file() or target.exists():
        raise ValueError('Invalid snapshot paths')
    if shutil.disk_usage(target.parent).free < source.stat().st_size * 2 + 100_000_000:
        raise OSError('Insufficient space')
    target.touch(mode=0o600)
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            with closing(sqlite3.connect(target)) as backup:
                db.backup(backup, pages=1024, sleep=0.1)
        verify_database(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def add_file(source, target):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Unsafe backup source')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o600)


def build_bundle(target, repo=REPO, database=DATABASE, env_file=ENV, config_files=None):
    """Database stores Library/ETA blobs; old backups, temp imports and SSH keys excluded."""
    target, repo = Path(target), Path(repo)
    configs = config_files if config_files is not None else [
        Path('/etc/nginx/nginx.conf'),
        Path('/usr/local/libexec/aborigen-crm-backup.py'),
        Path('/etc/letsencrypt/renewal-hooks/deploy/reload-nginx'),
        *Path('/etc/nginx').glob('conf.d/*.conf'),
        *Path('/etc/nginx').glob('sites-available/*'),
        *Path('/etc/systemd/system').glob('aborigen-crm*.*'),
    ]
    with tempfile.TemporaryDirectory(prefix='.bundle-', dir=target.parent) as work:
        root = Path(work)
        snapshot(database, root / 'db.sqlite3')
        add_file(env_file, root / 'settings/aborigen-crm.env')
        revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True, timeout=30).strip()
        dirty = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain', '--untracked-files=no'], timeout=30)
        if dirty:
            raise ValueError('Tracked application code has uncommitted changes')
        subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar.gz', '-o', str(root / 'code.tar.gz'), revision], check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        reference_paths = {}
        for index, source in enumerate(configs):
            # Configuration is reference material; restore does not activate it blindly.
            source = Path(source)
            if source.is_file() and not source.is_symlink():
                reference = Path('server-reference') / str(index) / source.name
                add_file(source, root / reference)
                reference_paths[reference.as_posix()] = str(source)
        manifest = {'format': FORMAT, 'created': stamp(), 'revision': revision,
                    'database': 'db.sqlite3', 'files': {}, 'reference_paths': reference_paths,
                    'note': 'Contains personal data and secrets. TLS certificates must be issued on the replacement server.'}
        for file in sorted(root.rglob('*')):
            if file.is_file():
                manifest['files'][file.relative_to(root).as_posix()] = {'sha256': digest(file), 'size': file.stat().st_size}
        (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        try:
            with tarfile.open(target, 'w:gz') as archive:
                for file in sorted(root.rglob('*')):
                    if file.is_file():
                        archive.add(file, arcname=file.relative_to(root).as_posix(), recursive=False)
            target.chmod(0o600)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return manifest


def unpack_verified(archive_path, destination):
    """Stage only in a new private directory. Never overwrite live data or follow links."""
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        with tarfile.open(archive_path, 'r:gz') as archive:
            members = archive.getmembers()
            names = [m.name for m in members]
            if len(names) != len(set(names)) or len(names) > 10000:
                raise ValueError('Invalid archive members')
            for member in members:
                path = Path(member.name)
                if not member.isfile() or path.is_absolute() or '..' in path.parts:
                    raise ValueError('Unsafe archive member')
            manifest_member = archive.getmember('manifest.json')
            if manifest_member.size > 2_000_000:
                raise ValueError('Invalid manifest size')
            manifest = json.load(archive.extractfile(manifest_member))
            if manifest.get('format') != FORMAT or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', manifest.get('revision', '')) or set(names) != set(manifest['files']) | {'manifest.json'}:
                raise ValueError('Invalid manifest')
            total = sum(m.size for m in members)
            if total > shutil.disk_usage(destination).free - 100_000_000:
                raise ValueError('Insufficient space for restore')
            for member in members:
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o600)
            for name, expected in manifest['files'].items():
                file = destination / name
                if file.stat().st_size != expected['size'] or digest(file) != expected['sha256']:
                    raise ValueError('Archive checksum mismatch')
        verify_database(destination / 'db.sqlite3')
        return manifest
    except Exception:
        shutil.rmtree(destination)
        raise


def restic_environment(config=Path('/etc/aborigen-crm-backup.env')):
    if config.is_symlink() or not config.is_file() or config.stat().st_mode & 0o077 or (os.geteuid() == 0 and config.stat().st_uid != 0):
        raise ValueError('Backup configuration must be private')
    values = {}
    allowed = {'RESTIC_REPOSITORY', 'RESTIC_PASSWORD_FILE', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_DEFAULT_REGION', 'RCLONE_CONFIG'}
    for line in config.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        if key not in allowed:
            raise ValueError('Unknown backup setting')
        parts = shlex.split(value)
        if len(parts) != 1:
            raise ValueError('Invalid backup setting')
        values[key] = parts[0]
    required = {'RESTIC_REPOSITORY', 'RESTIC_PASSWORD_FILE'}
    if not required <= values.keys():
        raise ValueError('Configure encrypted external repository')
    repository = values['RESTIC_REPOSITORY']
    if repository.startswith('s3:https://'):
        url = urlsplit(repository[3:])
        if not url.hostname or url.username or url.password or url.query or url.fragment or not url.path.strip('/'):
            raise ValueError('Use an HTTPS bucket URL without embedded credentials')
        if not {'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'} <= values.keys():
            raise ValueError('Configure S3 credentials')
    elif re.fullmatch(r'rclone:masterhost:[a-zA-Z0-9/_-]+', repository):
        remote_config = Path(values.get('RCLONE_CONFIG', '/root/.config/rclone/rclone.conf'))
        if remote_config.is_symlink() or not remote_config.is_file() or remote_config.stat().st_mode & 0o077 or (os.geteuid() == 0 and remote_config.stat().st_uid != 0):
            raise ValueError('Private rclone configuration required')
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(remote_config)
        remote = parser['masterhost']
        if remote.get('type') != 'ftp' or remote.get('explicit_tls', '').lower() != 'true':
            raise ValueError('Masterhost requires explicit FTPS with certificate verification')
        if remote.get('no_check_certificate', '').lower() == 'true' or remote.get('tls', '').lower() == 'true':
            raise ValueError('Do not weaken FTPS certificate verification')
        values['RCLONE_CONFIG'] = str(remote_config)
    else:
        raise ValueError('Use S3 HTTPS or configured Masterhost FTPS repository')
    password = Path(values['RESTIC_PASSWORD_FILE'])
    if password.is_symlink() or not password.is_file() or password.stat().st_mode & 0o077 or (os.geteuid() == 0 and password.stat().st_uid != 0) or not password.read_bytes().strip():
        raise ValueError('Restic password file must be private and nonempty')
    return {**os.environ, 'GOGC': '50', 'GOMEMLIMIT': '256MiB', 'RCLONE_NO_CHECK_CERTIFICATE': 'false', **values}


def upload_verified(bundle, environment, runner=subprocess.run):
    """Verify a complete encrypted repository round trip before deleting old snapshots."""
    with Path(bundle).open('rb') as source:
        result = runner(['restic', 'backup', '--json', '--stdin', '--stdin-filename', 'crm-full.tar.gz', '--host', 'aborigen-crm', '--tag', 'crm-recovery-v1'], stdin=source, env=environment, capture_output=True, timeout=1800, check=True)
    summaries = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    snapshot_id = next(item['snapshot_id'] for item in reversed(summaries) if item.get('message_type') == 'summary' and item.get('snapshot_id'))
    if not snapshot_id or any(c not in '0123456789abcdef' for c in snapshot_id):
        raise ValueError('Invalid remote snapshot ID')
    # Stream the restored archive to a hash, without buffering it in memory or on disk.
    process = subprocess.Popen(['restic', 'dump', snapshot_id, 'crm-full.tar.gz'], env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        import threading
        timer = threading.Timer(1800, process.kill)
        timer.start()
        actual = hashlib.file_digest(process.stdout, 'sha256').hexdigest()
        if process.wait(timeout=30) or actual != digest(bundle):
            raise ValueError('Remote backup verification failed')
    finally:
        timer.cancel()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()
    runner(['restic', 'forget', '--host', 'aborigen-crm', '--tag', 'crm-recovery-v1', '--group-by', 'host,paths,tags', '--keep-daily', '14', '--keep-monthly', '3', '--prune'], env=environment, capture_output=True, timeout=1800, check=True)
    return snapshot_id


def unpack_code(archive_path, destination):
    """Extract bundled source after verifying the containing recovery archive."""
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        with tarfile.open(archive_path, 'r:gz') as archive:
            members = archive.getmembers()
            names = [m.name.rstrip('/') for m in members]
            if len(names) > 10000 or len(names) != len(set(names)):
                raise ValueError('Invalid source archive')
            if sum(m.size for m in members) > shutil.disk_usage(destination).free - 100_000_000:
                raise ValueError('Insufficient space')
            for member in members:
                path = Path(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe source member')
            for member in members:
                target = destination / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
        if not (destination / 'manage.py').is_file() or not (destination / 'requirements.txt').is_file():
            raise ValueError('Not a CRM source archive')
    except Exception:
        shutil.rmtree(destination)
        raise
