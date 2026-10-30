#!/usr/bin/env python3
"""Enable HTTP/2 on the dedicated CRM Nginx site; preserve TLS versions and data."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SITE=Path('/etc/nginx/sites-available/aborigen-crm')


def configured(text):
    names=re.findall(r'^\s*server_name\s+([^;]+);',text,re.M)
    if not names or any(name.split()!=['crm.aborigen-tour.ru'] for name in names):
        raise ValueError('Файл содержит неизвестные виртуальные хосты. Изменения остановлены.')
    found=[]
    def change(match):
        tokens=match[2].split()
        if tokens[0]!='443' and not tokens[0].endswith(':443'):return match[0]
        if 'ssl' not in tokens or 'quic' in tokens:raise ValueError('Неожиданный HTTPS listen. Требуется ручная проверка.')
        found.append(True)
        return match[0] if 'http2' in tokens else match[1]+match[2].rstrip()+' http2;'
    result=re.sub(r'^(\s*listen\s+)([^;\n]+);',change,text,flags=re.M)
    if not found:raise ValueError('Не найден HTTPS listen на порту 443.')
    return result


def write_atomic(path,text):
    info=path.stat()
    fd,name=tempfile.mkstemp(prefix='.crm-http2-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,info.st_mode & 0o777)
        if os.geteuid()==0:os.chown(name,info.st_uid,info.st_gid)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def enable(path=SITE,backup_dir=Path('/root/crm-nginx-backups'),runner=subprocess.run):
    if path.is_symlink():raise ValueError('Неожиданная ссылка вместо файла сайта. Требуется проверка.')
    original=path.read_text();updated=configured(original)
    runner(['nginx','-t'],check=True)
    build=runner(['nginx','-V'],check=True,capture_output=True,text=True)
    if '--with-http_v2_module' not in build.stdout+build.stderr:raise ValueError('Nginx собран без поддержки HTTP/2.')
    if updated==original:print('HTTP/2 уже включён; файл не изменён.');return None
    backup_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    backup=backup_dir/('before-http2-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')+'.conf')
    shutil.copy2(path,backup);backup.chmod(0o600)
    write_atomic(path,updated)
    try:
        runner(['nginx','-t'],check=True)
        runner(['systemctl','reload','nginx'],check=True)
    except (subprocess.CalledProcessError,OSError):
        write_atomic(path,original)
        print('Исходный файл восстановлен. Проверьте nginx -t и состояние службы.')
        raise
    print('HTTP/2 включён. Версии TLS сохранены. Копия:',backup)
    return backup


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Сделать копию, включить HTTP/2 и плавно перечитать Nginx')
    args=parser.parse_args()
    try:
        if args.apply:
            if os.geteuid()!=0:raise ValueError('Запустите от root.')
            enable()
        else:
            updated=configured(SITE.read_text())
            print('Готово к включению HTTP/2. Для применения: --apply. База и приложение не изменяются.')
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        raise SystemExit('HTTP/2 не применён: '+str(exc))
