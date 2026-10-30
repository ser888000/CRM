"""Yandex supported IMAP SSL interface, read-only mailbox, durable UID cursor."""
import base64
import imaplib
import json
import os
import ssl
import time
from pathlib import Path
from .client import CRMClient
from .worker import private_write


def poll(client,path):
    state=json.loads(path.read_text()) if path.exists() else {}
    with imaplib.IMAP4_SSL(os.getenv('ETA_IMAP_HOST','imap.yandex.ru'),int(os.getenv('ETA_IMAP_PORT','993')),ssl_context=ssl.create_default_context(),timeout=30) as box:
        box.login(os.environ.get('ETA_IMAP_USER','spo-ab@ya.ru'),os.environ['ETA_IMAP_PASSWORD'])
        status,_=box.select(os.getenv('ETA_IMAP_FOLDER','INBOX'),readonly=True)
        if status!='OK':raise RuntimeError('Mailbox unavailable')
        validity=box.response('UIDVALIDITY')[1][0].decode()
        if state.get('uidvalidity')!=validity:state={'uidvalidity':validity,'last_uid':0}
        status,rows=box.uid('search',None,'ALL')
        if status!='OK':raise RuntimeError('UID search failed')
        uids=[int(v) for v in rows[0].split() if int(v)>state['last_uid']]
        if not state['last_uid']:uids=uids[-int(os.getenv('ETA_IMAP_INITIAL_LIMIT','200')):]
        for uid in uids[:100]:
            status,metadata=box.uid('fetch',str(uid),'(RFC822.SIZE)')
            import re
            size=re.search(rb'RFC822.SIZE\s+(\d+)',b' '.join(m for m in metadata if isinstance(m,bytes)))
            if not size or int(size[1])>2*1024*1024:
                # Oversized messages must be handled in mail UI; don't fill the CRM disk.
                print('ETA mailbox: oversized message requires mailbox review.',flush=True)
                state['last_uid']=uid;private_write(path,state);continue
            status,data=box.uid('fetch',str(uid),'(BODY.PEEK[])')
            if status!='OK':raise RuntimeError('Message fetch failed')
            raw=next(v[1] for v in data if isinstance(v,tuple))
            # Server is authoritative for identity/trust/type. Only probable ETA mail
            # is transferred; no arbitrary inbox copies, no deleting/marking messages.
            from email import policy
            from email.parser import BytesParser
            headers=BytesParser(policy=policy.default).parsebytes(raw,headersonly=True)
            subject=str(headers.get('Subject','')).lower()
            if any(word in subject for word in ('eta','visa','immigration','electronic travel author','approval notice')):
                client.post('mail/',{'eml_base64':base64.b64encode(raw).decode()})
            state['last_uid']=uid;private_write(path,state)


def main():
    os.umask(0o077)
    client=CRMClient(os.environ['ETA_CRM_URL'],os.environ['ETA_MAIL_TOKEN'])
    folder=Path(os.getenv('ETA_MAIL_STATE_DIR','/var/lib/eta-mail'));folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    while True:
        try:poll(client,folder/'cursor.json')
        except Exception:print('ETA mailbox temporarily unavailable; cursor retained. No submission started.',flush=True)
        time.sleep(60)


if __name__=='__main__':main()
