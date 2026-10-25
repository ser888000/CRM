"""Run only against the isolated READ_ONLY legacy clone; output contains private data."""
import base64
import hashlib
import json
import os
import sys
import zipfile
import pymssql


def main(path):
    connection=pymssql.connect(server='127.0.0.1',user='sa',password=os.environ['MSSQL_SA_PASSWORD'],database='legacy_crm',autocommit=True)
    cursor=connection.cursor(as_dict=True)
    cursor.execute("SELECT DATABASEPROPERTYEX(DB_NAME(),'Updateability') AS mode")
    mode=cursor.fetchone()['mode']
    if isinstance(mode,bytes):mode=mode.decode('ascii')
    if mode!='READ_ONLY':raise RuntimeError('A READ_ONLY clone is required')
    manifest={'format':'aborigen-legacy-library-v1','source_key':'masterhost:u340795_crm','snapshot':'2026-10-25T01:35:50','items':[],'files':[]}
    cursor.execute('SELECT ID_INFO_BASE,ID_RAZDEL_INFO_BASE,TEMA_NAME,CONVERT(varbinary(max),CONVERT(varchar(max),TEXT_INFO_BASE)) AS original FROM dbo.LIST_INFO_BASE ORDER BY ID_INFO_BASE')
    for row in cursor.fetchall():
        raw=bytes(row['original'] or b'')
        manifest['items'].append({'id':row['ID_INFO_BASE'],'parent':row['ID_RAZDEL_INFO_BASE'],'title':row['TEMA_NAME'] or '', 'encoding':'cp1251','original_b64':base64.b64encode(raw).decode('ascii'),'sha256':hashlib.sha256(raw).hexdigest()})
    cursor.execute('SELECT a.ID_LIST_ATACH_DOC,a.ID_INFO_BASE,a.FILE_NAME_ATACH,a.PRIM_ATTACH_DOC,a.DOC_STREAM,a.DATA_ATACH_DOC,a.DATA_RESAVE_DOC FROM dbo.LIST_ATACH_DOCUMENTS a JOIN dbo.LIST_INFO_BASE b ON b.ID_INFO_BASE=a.ID_INFO_BASE WHERE COALESCE(a.TRASH,0)=0 ORDER BY a.ID_LIST_ATACH_DOC')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
        for row in cursor.fetchall():
            raw=bytes(row['DOC_STREAM'] or b'');member=f"files/{row['ID_LIST_ATACH_DOC']}.bin"
            manifest['files'].append({'id':row['ID_LIST_ATACH_DOC'],'entry_id':row['ID_INFO_BASE'],'name':row['FILE_NAME_ATACH'] or '', 'notes':row['PRIM_ATTACH_DOC'] or '', 'member':member,'sha256':hashlib.sha256(raw).hexdigest(),'meta':{'attached_at':str(row['DATA_ATACH_DOC']) if row['DATA_ATACH_DOC'] else None,'resaved_at':str(row['DATA_RESAVE_DOC']) if row['DATA_RESAVE_DOC'] else None}})
            archive.writestr(member,raw)
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
    connection.close()
    print(f"Exported {len(manifest['items'])} entries and {len(manifest['files'])} library files")

if __name__=='__main__':main(sys.argv[1])
