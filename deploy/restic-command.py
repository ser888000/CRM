#!/usr/bin/python3
"""Run read-only restic recovery/check operations with private server settings."""
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from crm_recovery import restic_environment
except ImportError:
    from crm.recovery import restic_environment

args = sys.argv[1:]
if not args or args[0] not in ('snapshots', 'check', 'dump'):
    raise SystemExit('Allowed: snapshots, check, dump SNAPSHOT crm-full.tar.gz')
if args[0] == 'dump' and (len(args) != 3 or args[2] != 'crm-full.tar.gz' or not args[1] or any(c not in '0123456789abcdef' for c in args[1])):
    raise SystemExit('Use a specific snapshot ID and crm-full.tar.gz')
if args[0] != 'dump' and len(args) != 1:
    raise SystemExit('Extra arguments are not accepted')
try:
    env = restic_environment()
except Exception:
    raise SystemExit('Check private backup configuration')
# No subprocess exception text or stderr with potentially sensitive remote settings.
result = subprocess.run(['restic', *args], env=env, stderr=subprocess.DEVNULL)
if result.returncode:
    raise SystemExit('Restic operation failed; check connection, password and configuration')
