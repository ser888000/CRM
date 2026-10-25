"""Export approved history tables from the isolated READ_ONLY clone, never live SQL.
Output contains personal data and must stay outside Git/public directories.
"""
import datetime
import decimal
import json
import os
import sys
import zipfile
import pymssql

DOC_SCOPE='COALESCE(TRASH,0)=0 AND ID_TIP_DOC NOT IN (19,24)'


def main(path):
    c=pymssql.connect(server='127.0.0.1',user='sa',password=os.environ['MSSQL_SA_PASSWORD'],database='legacy_crm',autocommit=True)
    x=c.cursor(as_dict=True)
    x.execute("SELECT DATABASEPROPERTYEX(DB_NAME(),'Updateability') AS mode")
    mode=x.fetchone()['mode']
    if mode not in ('READ_ONLY',b'READ_ONLY'):raise RuntimeError('READ_ONLY clone required')
    def rows(sql):
        x.execute(sql)
        return x.fetchall()
    docs=rows('SELECT * FROM dbo.LIST_DOCUMENTS WHERE '+DOC_SCOPE)
    payments=rows('SELECT * FROM dbo.LIST_MANYS WHERE COALESCE(TRASH,0)=0')
    tasks=rows('SELECT * FROM dbo.LIST_CONTACT_COMPANY WHERE COALESCE(TRASH,0)=0')
    needed={r['ID_COMPANY'] for r in docs+payments+tasks}
    customers=[r for r in rows('SELECT * FROM dbo.COMPANY') if not r['TRASH'] or r['ID_COMPANY'] in needed]
    customer_ids={r['ID_COMPANY'] for r in customers};doc_ids={r['ID_DOC'] for r in docs}
    tables={'COMPANY':customers,'LIST_DOCUMENTS':docs,'LIST_MANYS':payments,'LIST_CONTACT_COMPANY':tasks}
    for table,key,ids in [('LIST_TOVAR_DOC','ID_DOC',doc_ids),('LIST_TELEPHONES','ID_COMPANY',customer_ids),('LIST_EMAIL_CLIENT','ID_COMPANY',customer_ids),('LIST_REQUIS_FIZ','ID_COMPANY',customer_ids),('LIST_REQUIS_COMPANY','ID_COMPANY',customer_ids)]:
        tables[table]=[r for r in rows('SELECT * FROM dbo.'+table) if r[key] in ids]
    for table in ['PRIZNAK_DOCUMENTS','TIP_DOCUMENTS','VID_CONTACT','VID_COMPANY','LIST_VALUTA','LIST_SPR_SCHETS_MONY','ADD_SPR_OPEROTOR','ADD_SPR_PITANIE','ADD_SPR_TRANSFER','ADD_SPR_STRAHOVKA','ADD_SPR_country','ADD_SPR_city_fly']:
        columns={'PRIZNAK_DOCUMENTS':'ID_PRIZNAK_DOCUMENT,PRIZNAK_DOCUMENT','TIP_DOCUMENTS':'ID_TIP_DOCUMENT,TIP_DOCUMENT','VID_CONTACT':'ID_VID_CONTACT,DISCRIPTION_VID_CONTCT','VID_COMPANY':'ID_VID_COMPANY,DISCRIPTION','LIST_VALUTA':'id_valuta,NAME_VALUTA,CODE,NCODE','LIST_SPR_SCHETS_MONY':'ID_LIST_SPR_LIST_SCHETS_MONY,NAME_SCHET,ID_VALUTA'}
        tables[table]=rows('SELECT '+columns.get(table,'id,name')+' FROM dbo.'+table)
    # Explicit allowlist: no passwords, SIP credentials, tokens or integration settings.
    tables['MANAGERS']=rows('SELECT ID_MANAGER,MANAGER_NAME FROM dbo.MANAGERS')
    manifest={'format':'aborigen-legacy-history-v2','source_key':'masterhost:u340795_crm','snapshot':'2026-10-25T01:35:50','tables':tables}
    def encode(value):
        if isinstance(value,(datetime.datetime,datetime.date,datetime.time)):return value.isoformat()
        if isinstance(value,decimal.Decimal):return str(value)
        if isinstance(value,bytes):raise ValueError('Unexpected binary column in history')
        raise TypeError(type(value).__name__)
    data=json.dumps(manifest,ensure_ascii=False,default=encode,allow_nan=False).encode('utf-8')
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('history.json',data)
    print(json.dumps({'rows':{k:len(v) for k,v in tables.items()},'expanded_bytes':len(data),'package_bytes':os.path.getsize(path)}))
    c.close()

if __name__=='__main__':main(sys.argv[1])
