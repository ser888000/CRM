#!/usr/bin/python3
"""Verify and stage a recovery archive. Never modify a running CRM."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from crm_recovery import unpack_verified, unpack_code
except ImportError:
    from crm.recovery import unpack_verified, unpack_code

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('archive', type=Path)
parser.add_argument('--code-only', action='store_true', help='Extract source from an already verified full archive')
parser.add_argument('--stage', required=True, type=Path, help='New directory; must not exist')
args = parser.parse_args()
try:
    result = None if args.code_only else unpack_verified(args.archive, args.stage)
    if args.code_only:
        unpack_code(args.archive, args.stage)
except Exception:
    raise SystemExit('Archive verification failed. Live application unchanged.')
print('Verified and staged. Live application unchanged.')
if result:
    print('Version:', result['revision'])
print('Staging directory:', args.stage)
