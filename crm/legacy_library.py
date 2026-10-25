"""Validated, transactional library-only import. No archive member is executed/extracted."""
import base64
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath
from django.db import transaction
from .models import LibraryEntry,LibraryAttachment,LegacyImportRun,AuditEvent,normalize_location

MAX_PACKAGE=8*1024*1024
MAX_EXPANDED=64*1024*1024
MAX_ORIGINAL=1024*1024
MAX_FILE=16*1024*1024

class LibraryImportError(ValueError):pass


def integer(value,positive=False):
    if type(value) is not int or abs(value)>2147483647 or positive and value<1:raise LibraryImportError('Некорректный идентификатор в пакете.')
    return value


def text(value,limit):
    if not isinstance(value,str) or len(value)>limit or '\x00' in value or any(0xd800<=ord(c)<=0xdfff for c in value):raise LibraryImportError('Некорректное текстовое поле в пакете.')
    return value


def filename(value,source_id):
    name=PurePosixPath(text(value,1000).replace('\\','/')).name
    name=''.join(c for c in name if ord(c)>=32 and ord(c)!=127)[:250]
    return name if name not in ('','.','..') else f'file-{source_id}'


def load_package(stream):
    blob=stream.read(MAX_PACKAGE+1)
    if len(blob)>MAX_PACKAGE:raise LibraryImportError('Пакет библиотеки должен быть не больше 8 МБ.')
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            members=archive.infolist();names=[m.filename for m in members]
            if len(members)>4000 or len(names)!=len(set(names)) or sum(m.file_size for m in members)>MAX_EXPANDED:raise LibraryImportError('Слишком большой или некорректный архив.')
            for member in members:
                path=PurePosixPath(member.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in member.filename or stat.S_ISLNK(member.external_attr>>16):raise LibraryImportError('Недопустимый путь в архиве.')
            if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>12*1024*1024:raise LibraryImportError('Не найден манифест пакета библиотеки.')
            manifest=json.loads(archive.read('manifest.json').decode('utf-8'))
            if not isinstance(manifest,dict) or manifest.get('format')!='aborigen-legacy-library-v1':raise LibraryImportError('Это не подготовленный пакет библиотеки.')
            source=text(manifest.get('source_key'),100)
            if not re.fullmatch('[a-zA-Z0-9:_-]+',source):raise LibraryImportError('Некорректный источник пакета.')
            items=manifest.get('items');files=manifest.get('files')
            if not isinstance(items,list) or not isinstance(files,list) or not 1<=len(items)<=3000 or len(files)>1000:raise LibraryImportError('Некорректное количество разделов или файлов.')
            entries=[];ids=set();fingerprints=[]
            for item in items:
                if not isinstance(item,dict):raise LibraryImportError('Некорректная запись раздела.')
                key=integer(item.get('id'),True)
                if key in ids:raise LibraryImportError('Повторяется идентификатор раздела.')
                ids.add(key);parent=item.get('parent')
                if parent is not None:integer(parent)
                title=text(item.get('title',''),500);encoding=item.get('encoding','cp1251')
                if encoding not in ('cp1251','cp1252','utf-8'):raise LibraryImportError('Неизвестная кодировка текста.')
                encoded=text(item.get('original_b64',''),2*MAX_ORIGINAL)
                original=base64.b64decode(encoded,validate=True)
                if len(original)>MAX_ORIGINAL:raise LibraryImportError('Слишком большой текст раздела.')
                digest=hashlib.sha256(original).hexdigest()
                if digest!=item.get('sha256'):raise LibraryImportError('Не совпала контрольная сумма текста.')
                entries.append({'id':key,'parent':parent,'title':title,'original':original,'encoding':encoding})
                fingerprints.append({'id':key,'parent':parent,'title':title,'sha256':digest,'encoding':encoding})
            parents={e['id']:e['parent'] for e in entries}
            for entry in entries:
                seen=set();node=entry['id']
                while node in parents:
                    if node in seen or len(seen)>100:raise LibraryImportError('Цикл или слишком большая вложенность разделов.')
                    seen.add(node);node=parents[node]
            attachments=[];file_ids=set();expected={'manifest.json'}
            file_fingerprints=[]
            for file in files:
                if not isinstance(file,dict):raise LibraryImportError('Некорректная запись файла.')
                key=integer(file.get('id'),True);entry_id=integer(file.get('entry_id'),True)
                if key in file_ids or entry_id not in ids:raise LibraryImportError('Файл повторяется или не связан с разделом библиотеки.')
                file_ids.add(key);member=text(file.get('member'),200)
                if member!=f'files/{key}.bin' or member not in names or archive.getinfo(member).file_size>MAX_FILE:raise LibraryImportError('Некорректный файл в пакете.')
                data=archive.read(member);digest=hashlib.sha256(data).hexdigest()
                if digest!=file.get('sha256'):raise LibraryImportError('Не совпала контрольная сумма файла.')
                name=filename(file.get('name',''),key);notes=text(file.get('notes',''),10000)
                meta=file.get('meta',{})
                if not isinstance(meta,dict) or set(meta)-{'attached_at','resaved_at'} or any(not isinstance(v,(str,type(None))) or isinstance(v,str) and len(v)>64 for v in meta.values()):raise LibraryImportError('Некорректные даты файла.')
                attachments.append({'id':key,'entry_id':entry_id,'name':name,'notes':notes,'meta':meta,'data':data,'sha256':digest})
                file_fingerprints.append({'id':key,'entry_id':entry_id,'name':name,'notes':notes,'meta':meta,'sha256':digest})
                expected.add(member)
            if set(names)!=expected:raise LibraryImportError('В архиве есть посторонние файлы.')
            signature={'source':source,'items':sorted(fingerprints,key=lambda e:e['id']),'files':sorted(file_fingerprints,key=lambda e:e['id'])}
            digest=hashlib.sha256(json.dumps(signature,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            return {'source':source,'snapshot':text(manifest.get('snapshot',''),64),'entries':entries,'files':attachments,'digest':digest}
    except LibraryImportError:raise
    except (zipfile.BadZipFile,KeyError,ValueError,TypeError,RuntimeError,UnicodeError,OSError,NotImplementedError) as error:
        raise LibraryImportError('Пакет повреждён или имеет неверный формат.') from error


@transaction.atomic
def apply_package(package,actor=None):
    from striprtf.striprtf import rtf_to_text
    source=package['source']
    run,created=LegacyImportRun.objects.get_or_create(source_key=source,section='library',content_sha256=package['digest'],defaults={'actor':actor,'source_snapshot':package['snapshot']})
    run=LegacyImportRun.objects.select_for_update().get(pk=run.pk)
    if not created:
        if run.library_entries.count()!=run.summary.get('entries') or LibraryAttachment.objects.filter(entry__import_run=run).count()!=run.summary.get('files'):raise LibraryImportError('Состав ранее загруженной библиотеки изменился. Повторная загрузка остановлена.')
        return run,False
    if LibraryEntry.objects.filter(source_key=source,source_id__in=[v['id'] for v in package['entries']]).exists():raise LibraryImportError('Библиотека из этого источника уже есть. Загрузка изменённого снимка требует отдельной сверки.')
    entries=[];issues=[]
    for item in package['entries']:
        original=item['original'];decoded=original.decode(item['encoding'],errors='replace');fmt='rtf' if original.lstrip().startswith(b'{\\rtf') else 'text'
        try:body=rtf_to_text(decoded,encoding=item['encoding'],errors='replace') if fmt=='rtf' else decoded
        except (ValueError,UnicodeError,IndexError,OverflowError):
            body='';issues.append({'kind':'text_conversion','source_id':item['id']})
        # RTF Unicode escapes may produce UTF-16 surrogate pairs.
        body=body.encode('utf-16-le',errors='surrogatepass').decode('utf-16-le',errors='replace')
        entries.append(LibraryEntry(title=item['title'],body=body,search_text=normalize_location(item['title']+' '+body),original_data=original,original_format=fmt,sort_order=item['id'],source_key=source,source_id=item['id'],source_parent_id=item['parent'],import_run=run))
    LibraryEntry.objects.bulk_create(entries)
    lookup={e.source_id:e for e in entries}
    for entry in entries:
        if entry.source_parent_id in lookup:entry.parent=lookup[entry.source_parent_id]
        elif entry.source_parent_id not in (None,-1,0):issues.append({'kind':'missing_parent','source_id':entry.source_id,'parent_source_id':entry.source_parent_id})
    LibraryEntry.objects.bulk_update(entries,['parent'])
    LibraryAttachment.objects.bulk_create([LibraryAttachment(entry=lookup[f['entry_id']],original_name=f['name'],notes=f['notes'],data=f['data'],byte_size=len(f['data']),sha256=f['sha256'],source_id=f['id'],source_meta=f['meta']) for f in package['files']])
    run.summary={'entries':len(entries),'files':len(package['files']),'texts':sum(bool(e.original_data) for e in entries),'issues':len(issues)};run.issues=issues;run.save(update_fields=['summary','issues'])
    AuditEvent.objects.create(actor=actor,object_type='crm.LegacyImportRun',object_id=str(run.pk),action='library_imported',changes=run.summary)
    return run,True
