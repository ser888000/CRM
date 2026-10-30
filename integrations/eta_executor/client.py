import json
import os
import ssl
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.parse import urlsplit


class CRMClient:
    def __init__(self,base,token,worker_id=None):
        url=urlsplit(base)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):raise ValueError('CRM base must be an HTTPS origin')
        self.base=base.rstrip('/');self.token=token;self.worker_id=worker_id
    def post(self,path,data):
        if self.worker_id:data={**data,'worker_id':self.worker_id}
        request=Request(self.base+'/api/eta/v1/'+path.lstrip('/'),data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
        # Never retry mutations automatically, especially begin-submission/result.
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=build_opener(HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
        with opener.open(request,timeout=40) as response:return json.load(response)
