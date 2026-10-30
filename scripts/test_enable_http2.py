import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

spec=importlib.util.spec_from_file_location('http2',Path('deploy/enable-http2.py'))
http2=importlib.util.module_from_spec(spec);spec.loader.exec_module(http2)
CONFIG='''server {
 listen 80;
 server_name crm.aborigen-tour.ru;
 location / { return 301 https://crm.aborigen-tour.ru$request_uri; }
}
server {
 listen 443 ssl;
 server_name crm.aborigen-tour.ru;
 ssl_protocols TLSv1.2 TLSv1.3;
 ssl_certificate /etc/letsencrypt/live/crm.aborigen-tour.ru/fullchain.pem;
 location / { proxy_pass http://127.0.0.1:8000; }
}
'''

class HTTP2Tests(unittest.TestCase):
 def test_preserves_tls_and_other_directives_and_is_idempotent(self):
  changed=http2.configured(CONFIG)
  self.assertEqual(changed,CONFIG.replace('listen 443 ssl;','listen 443 ssl http2;'))
  self.assertEqual(http2.configured(changed),changed)
 def test_rejects_unexpected_sites_or_non_ssl(self):
  for source in (CONFIG.replace('crm.aborigen-tour.ru;','other.invalid;'),CONFIG.replace('443 ssl;','443;'),CONFIG.replace('443 ssl;','8443 ssl;')):
   with self.assertRaises(ValueError):http2.configured(source)
 def test_apply_backs_up_before_reload(self):
  with tempfile.TemporaryDirectory() as folder:
   site=Path(folder)/'site';site.write_text(CONFIG);calls=[]
   def run(args,**kwargs):calls.append(args);return SimpleNamespace(stdout='',stderr='--with-http_v2_module')
   backup=http2.enable(site,Path(folder)/'backups',run)
   self.assertEqual(backup.read_text(),CONFIG);self.assertIn('443 ssl http2;',site.read_text());self.assertEqual(calls[-1],['systemctl','reload','nginx'])
 def test_validation_failure_restores_file_and_never_reloads(self):
  with tempfile.TemporaryDirectory() as folder:
   site=Path(folder)/'site';site.write_text(CONFIG);calls=[]
   def run(args,**kwargs):
    calls.append(args)
    if args==['nginx','-t'] and calls.count(args)>1:raise subprocess.CalledProcessError(1,args)
    return SimpleNamespace(stdout='',stderr='--with-http_v2_module')
   with self.assertRaises(subprocess.CalledProcessError):http2.enable(site,Path(folder)/'backups',run)
   self.assertEqual(site.read_text(),CONFIG);self.assertNotIn(['systemctl','reload','nginx'],calls)
