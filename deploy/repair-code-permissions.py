#!/usr/bin/python3
"""Repair public tracked code permissions without opening secrets or user data."""
import os
import subprocess
from pathlib import Path

REPO=Path('/opt/aborigen-crm')


def repair(repo=REPO):
    base=repo.resolve()
    entries=subprocess.check_output(['git','ls-files','--stage','-z'],cwd=base).decode('utf-8',errors='surrogateescape').split('\0')
    directories={base};count=0
    for entry in entries:
        if not entry:continue
        metadata,name=entry.split('\t',1);mode=metadata.split()[0]
        if mode not in ('100644','100755'):continue
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Invalid tracked path')
        file=base/relative
        if not file.exists():continue
        if file.is_symlink() or not file.resolve().is_relative_to(base):raise RuntimeError('Tracked code path contains a symlink')
        parent=file.parent
        while parent!=base:
            if parent.is_symlink():raise RuntimeError('Tracked code directory contains a symlink')
            directories.add(parent);parent=parent.parent
        file.chmod(0o755 if mode=='100755' else 0o644);count+=1
    for folder in directories:folder.chmod(0o755)
    return count

if __name__=='__main__':print(f'Code permissions repaired: {repair()} tracked files')
