import importlib.util
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from django.test import TestCase,SimpleTestCase,Client,override_settings
from django.contrib.auth import get_user_model
from .models import AuditEvent,Contract,Customer,Operator,ContractLine

class UpdateWebTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.folder=Path(self.directory.name);self.request_path=self.folder/'request.json';self.state_folder=self.folder/'state';self.state_folder.mkdir()
        self.settings_override=override_settings(CRM_UPDATE_REQUEST=str(self.request_path),CRM_UPDATE_STATE=str(self.state_folder));self.settings_override.enable();self.addCleanup(self.settings_override.disable)
        self.user=get_user_model().objects.create_superuser('admin','admin@example.test','test-password');self.client.force_login(self.user)
    def ready(self):(self.state_folder/'installed').touch()
    def test_only_superuser_and_csrf_can_request_update(self):
        self.ready();ordinary=get_user_model().objects.create_user('staff',is_staff=True);self.client.force_login(ordinary)
        for url in ('/management/update/','/management/update/status/'):
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.post('/management/update/start/').status_code,403);self.assertFalse(self.request_path.exists())
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post('/management/update/start/').status_code,403)
        self.client.force_login(self.user);self.assertEqual(self.client.get('/management/update/start/').status_code,405)
    def test_atomic_request_and_duplicate_click_and_audit(self):
        self.ready()
        for _ in range(2):self.assertEqual(self.client.post('/management/update/start/',{'command':'ignored','branch':'untrusted'}).status_code,302)
        data=json.loads(self.request_path.read_text());self.assertEqual(data['actor_id'],self.user.pk);uuid.UUID(data['request_id'])
        self.assertNotIn('command',data);self.assertNotIn('branch',data);self.assertEqual(AuditEvent.objects.filter(object_type='system.Update').count(),1)
        self.assertEqual(self.client.get('/management/update/status/').json()['state'],'queued')
        self.assertEqual(self.request_path.stat().st_mode&0o777,0o600);self.assertFalse(list(self.folder.glob('.update-*')))
    def test_disabled_without_bootstrap_and_terminal_failure_status(self):
        self.assertEqual(self.client.post('/management/update/start/').status_code,503);self.assertFalse(self.request_path.exists())
        self.ready();(self.state_folder/'status.json').write_text(json.dumps({'state':'failed','message':'Проверка','recovery_failed':True}))
        self.assertEqual(self.client.post('/management/update/start/').status_code,503);self.assertFalse(self.request_path.exists())
    def test_status_log_masking_and_maintenance_allows_status_only(self):
        self.ready();(self.state_folder/'latest.log').write_text('https://user:password@example.test/?authkey=VALUE secret=HIDDEN')
        data=self.client.get('/management/update/status/').json();self.assertNotIn('password',data['log']);self.assertNotIn('VALUE',data['log']);self.assertNotIn('HIDDEN',data['log'])
        (self.state_folder/'maintenance').touch()
        self.assertEqual(self.client.get('/').status_code,503)
        self.assertEqual(self.client.post('/finances/new/',{}).status_code,503)
        self.assertEqual(self.client.get('/management/update/status/').status_code,200)
        self.assertEqual(self.client.get('/health/').content,b'ok')
    def test_contract_adults_children_totals_follow_filters(self):
        customer=Customer.objects.create(name='Клиент');operator=Operator.objects.create(name='ТО')
        for index in (1,2):
            c=Contract.objects.create(customer=customer,operator=operator,number=str(index),adults=index,children=index+1)
            ContractLine.objects.create(contract=c,description='Тур',amount=100)
        response=self.client.get('/?f_number=1')
        footer={v['key']:v['text'] for v in response.context['footer']}
        self.assertEqual(footer['adults'],'1');self.assertEqual(footer['children'],'2');self.assertEqual(footer['amount'],'100,00')

class UpdateWorkerTests(SimpleTestCase):
    def setUp(self):
        path=Path(__file__).resolve().parent.parent/'deploy/run-update.py'
        spec=importlib.util.spec_from_file_location('update_worker',path);self.worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.worker)
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup);self.folder=Path(self.directory.name)
        for key in ('STATE','BACKUPS'):
            folder=self.folder/key;folder.mkdir();setattr(self.worker,key,folder)
        self.worker.REQUEST=self.folder/'request.json';self.worker.LOCK=self.folder/'lock';self.worker.DB=self.folder/'db.sqlite3';self.worker.ENV=self.folder/'crm.env'
        self.worker.ENV.write_text('CRM_DATABASE_PATH='+str(self.worker.DB)+'\n')
        self.worker.REQUEST.write_text(json.dumps({'request_id':str(uuid.uuid4()),'actor_id':1}))
        with sqlite3.connect(self.worker.DB) as db:db.execute('CREATE TABLE example (value INTEGER)');db.execute('INSERT INTO example VALUES (7)')
        account=SimpleNamespace(pw_uid=os.getuid(),pw_gid=os.getgid())
        self.patch_user=patch.object(self.worker.pwd,'getpwnam',return_value=account);self.patch_user.start();self.addCleanup(self.patch_user.stop)
        self.chown=patch.object(self.worker.os,'chown');self.chown.start();self.addCleanup(self.chown.stop)
    def git(self,*args):
        return {('remote','get-url','origin'):'https://github.com/ser888000/CRM.git',('status','--porcelain'):'',('rev-parse','HEAD'):'a'*40,('rev-parse','refs/remotes/origin/main'):'b'*40}[args]
    def result(self):return json.loads((self.worker.STATE/'status.json').read_text())
    def test_backup_and_restore_consistent_database(self):
        copy=self.folder/'copy.sqlite3';self.worker.backup_database(copy)
        with sqlite3.connect(self.worker.DB) as db:db.execute('UPDATE example SET value=9')
        self.worker.restore_database(copy)
        with sqlite3.connect(self.worker.DB) as db:self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0],7)
    def test_success_fixed_commands_backup_and_cleanup(self):
        with patch.object(self.worker,'git',side_effect=self.git),patch.object(self.worker,'run') as run,patch.object(self.worker,'healthy'):
            self.worker.main()
        self.assertEqual(self.result()['state'],'success');self.assertFalse(self.worker.REQUEST.exists());self.assertFalse((self.worker.STATE/'maintenance').exists())
        self.assertTrue(list(self.worker.BACKUPS.glob('*.sqlite3')))
        commands=[call.args[0] for call in run.call_args_list]
        self.assertIn(['bash','deploy/install-service.sh'],commands);self.assertIn(['git','merge','--ff-only','b'*40],commands)
    def test_migration_failure_restores_old_code_and_database(self):
        installs=0
        def run(args,*unused):
            nonlocal installs
            if args==['bash','deploy/install-service.sh']:
                installs+=1
                if installs==1:
                    with sqlite3.connect(self.worker.DB) as db:db.execute('UPDATE example SET value=99')
                    raise RuntimeError('Migration failed')
        with patch.object(self.worker,'git',side_effect=self.git),patch.object(self.worker,'run',side_effect=run) as command,patch.object(self.worker,'healthy'):
            self.worker.main()
        self.assertEqual(installs,2);self.assertEqual(self.result()['state'],'failed');self.assertIn('восстановлены',self.result()['message'])
        with sqlite3.connect(self.worker.DB) as db:self.assertEqual(db.execute('SELECT value FROM example').fetchone()[0],7)
        self.assertIn(['git','reset','--hard','a'*40],[call.args[0] for call in command.call_args_list])
    def test_failed_backup_does_not_restore_incomplete_file(self):
        with patch.object(self.worker,'git',side_effect=self.git),patch.object(self.worker,'run'),patch.object(self.worker,'healthy'),patch.object(self.worker,'backup_database',side_effect=OSError('Disk full')),patch.object(self.worker,'restore_database') as restore:
            self.worker.main()
        restore.assert_not_called();self.assertEqual(self.result()['state'],'failed')
    def test_dirty_checkout_and_interrupted_update_are_not_overwritten(self):
        def dirty(*args):return ' M file.py' if args==('status','--porcelain') else self.git(*args)
        with patch.object(self.worker,'git',side_effect=dirty),patch.object(self.worker,'run') as run:self.worker.main()
        run.assert_not_called();self.assertEqual(self.result()['state'],'failed')
        self.worker.REQUEST.write_text(json.dumps({'request_id':str(uuid.uuid4()),'actor_id':1}));(self.worker.STATE/'maintenance').touch()
        with patch.object(self.worker,'run') as run:self.worker.main()
        run.assert_not_called();self.assertTrue(self.result()['recovery_failed']);self.assertTrue((self.worker.STATE/'maintenance').exists())
    def test_symlink_request_cannot_be_read(self):
        self.worker.REQUEST.unlink();self.worker.REQUEST.symlink_to(self.worker.DB)
        with self.assertRaises(OSError):self.worker.read_request()

    def test_restore_does_not_follow_preexisting_temporary_symlink(self):
        backup=self.folder/'copy.sqlite3';self.worker.backup_database(backup)
        target=self.folder/'unrelated.txt';target.write_text('unchanged')
        self.worker.DB.with_suffix('.restore').symlink_to(target)
        self.worker.restore_database(backup)
        self.assertEqual(target.read_text(),'unchanged')

    def test_failed_recovery_preserves_maintenance_and_blocks_retries(self):
        def fail_install(args,*unused):
            if args==['bash','deploy/install-service.sh']:raise RuntimeError('Install failed')
        with patch.object(self.worker,'git',side_effect=self.git),patch.object(self.worker,'run',side_effect=fail_install):
            self.worker.main()
        self.assertEqual(self.result()['state'],'failed');self.assertTrue(self.result()['recovery_failed'])
        self.assertTrue((self.worker.STATE/'maintenance').exists());self.assertFalse(self.worker.REQUEST.exists())

    def test_unsupported_database_refuses_update_before_stopping(self):
        self.worker.ENV.write_text('CRM_DATABASE_PATH='+str(self.worker.DB)+'\nPOSTGRES_HOST=example.test\n')
        with patch.object(self.worker,'git',side_effect=self.git),patch.object(self.worker,'run') as run:self.worker.main()
        run.assert_not_called();self.assertEqual(self.result()['state'],'failed');self.assertFalse((self.worker.STATE/'maintenance').exists())
