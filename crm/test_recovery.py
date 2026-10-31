import io
import json
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, Client, override_settings
from .recovery import snapshot, build_bundle, unpack_verified, digest, restic_environment, upload_verified, unpack_code


def database(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE example (data BLOB)')
        db.execute('INSERT INTO example VALUES (?)', (b'fictional library document',))


class RecoveryArchiveTests(SimpleTestCase):
    def test_live_wal_snapshot_is_complete_and_does_not_copy_uncommitted_data(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp)/'source.sqlite3', Path(temp)/'copy.sqlite3'
            database(source)
            with sqlite3.connect(source) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('INSERT INTO example VALUES (?)', (b'uncommitted',))
                snapshot(source, target)
                with sqlite3.connect(target) as saved:
                    self.assertEqual(saved.execute('SELECT data FROM example').fetchall(), [(b'fictional library document',)])
                writer.rollback()
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def make_archive(self, root):
        repo=root/'repo';repo.mkdir()
        subprocess.run(['git','init','-q',str(repo)],check=True)
        (repo/'README').write_text('Recovery fixture')
        subprocess.run(['git','-C',str(repo),'add','README'],check=True)
        subprocess.run(['git','-C',str(repo),'-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','fixture'],check=True)
        source=root/'db.sqlite3';database(source)
        env=root/'settings.env';env.write_text('DJANGO_SECRET_KEY=fictional-test-key\n')
        archive=root/'full.tar.gz'
        manifest=build_bundle(archive,repo,source,env,config_files=[])
        return archive,manifest

    def test_full_archive_restores_code_settings_and_library_blob_with_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive,manifest=self.make_archive(root)
            stage=root/'restore'
            result=unpack_verified(archive,stage)
            self.assertEqual(result['revision'],manifest['revision'])
            self.assertEqual((stage/'settings/aborigen-crm.env').read_text(),'DJANGO_SECRET_KEY=fictional-test-key\n')
            with sqlite3.connect(stage/'db.sqlite3') as db:
                self.assertEqual(db.execute('SELECT data FROM example').fetchone()[0],b'fictional library document')
            with tarfile.open(stage/'code.tar.gz') as code:
                self.assertEqual(code.extractfile('README').read(),b'Recovery fixture')
            with self.assertRaises(FileExistsError):unpack_verified(archive,stage)
            self.assertTrue(stage.is_dir())

    def test_tampered_archive_and_path_traversal_rejected_without_live_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive,_=self.make_archive(root)
            bad=root/'bad.tar.gz'
            with tarfile.open(archive) as source,tarfile.open(bad,'w:gz') as dest:
                for member in source.getmembers():
                    data=source.extractfile(member).read()
                    if member.name=='settings/aborigen-crm.env':data=b'changed secret'
                    member.size=len(data);dest.addfile(member,io.BytesIO(data))
            with self.assertRaises(ValueError):unpack_verified(bad,root/'bad-stage')
            self.assertFalse((root/'bad-stage').exists())
            with tarfile.open(bad,'w:gz') as dest:
                member=tarfile.TarInfo('../escape');member.size=1;dest.addfile(member,io.BytesIO(b'x'))
            with self.assertRaises(ValueError):unpack_verified(bad,root/'bad-stage')
            self.assertFalse((root/'escape').exists())

    def test_secret_configuration_requires_private_permissions_and_https(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);password=root/'password';password.write_text('fictional password');password.chmod(0o600)
            config=root/'backup.env';config.write_text(f'RESTIC_REPOSITORY=s3:https://storage.example.test/bucket/crm\nRESTIC_PASSWORD_FILE={password}\nAWS_ACCESS_KEY_ID=fictional\nAWS_SECRET_ACCESS_KEY=fictional\n');config.chmod(0o600)
            self.assertIn('RESTIC_REPOSITORY',restic_environment(config))
            config.chmod(0o644)
            with self.assertRaises(ValueError):restic_environment(config)
            config.chmod(0o600);config.write_text(config.read_text().replace('https://','http://'))
            with self.assertRaises(ValueError):restic_environment(config)

    def test_masterhost_requires_private_explicit_ftps_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);password=root/'password';password.write_text('fictional');password.chmod(0o600)
            remote=root/'rclone.conf';remote.write_text('[masterhost]\ntype = ftp\nhost = ftp.example.test\nexplicit_tls = true\ntls = false\n');remote.chmod(0o600)
            config=root/'backup.env';config.write_text(f'RESTIC_REPOSITORY=rclone:masterhost:crm-backups\nRESTIC_PASSWORD_FILE={password}\nRCLONE_CONFIG={remote}\n');config.chmod(0o600)
            self.assertEqual(restic_environment(config)['RCLONE_CONFIG'],str(remote))
            remote.write_text(remote.read_text().replace('explicit_tls = true','explicit_tls = false'))
            with self.assertRaises(ValueError):restic_environment(config)
            remote.write_text('[masterhost]\ntype = ftp\nexplicit_tls = true\nno_check_certificate = true\n')
            with self.assertRaises(ValueError):restic_environment(config)

    def test_offline_code_restore_rejects_links_and_preserves_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'code.tar.gz'
            with tarfile.open(archive,'w:gz') as dest:
                for name in ['manage.py','requirements.txt']:
                    member=tarfile.TarInfo(name);member.size=4;dest.addfile(member,io.BytesIO(b'test'))
            unpack_code(archive,root/'code')
            self.assertEqual((root/'code/manage.py').read_text(),'test')
            with self.assertRaises(FileExistsError):unpack_code(archive,root/'code')
            with tarfile.open(archive,'w:gz') as dest:
                member=tarfile.TarInfo('link');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';dest.addfile(member)
            with self.assertRaises(ValueError):unpack_code(archive,root/'unsafe')
            self.assertFalse((root/'unsafe').exists())

    def test_remote_round_trip_failure_never_deletes_old_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle=Path(temp)/'bundle';bundle.write_bytes(b'archive content')
            runner=Mock(return_value=SimpleNamespace(stdout=b'{"message_type":"summary","snapshot_id":"abc123"}\n'))
            process=Mock(stdout=io.BytesIO(b'corrupt remote content'));process.wait.return_value=0;process.poll.return_value=0
            with patch('crm.recovery.subprocess.Popen',return_value=process):
                with self.assertRaises(ValueError):upload_verified(bundle,{},runner)
            self.assertEqual(runner.call_count,1)
            process=Mock(stdout=io.BytesIO(bundle.read_bytes()));process.wait.return_value=0;process.poll.return_value=0
            runner.reset_mock()
            with patch('crm.recovery.subprocess.Popen',return_value=process):self.assertEqual(upload_verified(bundle,{},runner),'abc123')
            self.assertEqual(runner.call_args.args[0][:2],['restic','forget'])


class RecoveryViewsTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.state=root/'state';self.state.mkdir();(self.state/'downloads').mkdir()
        self.request=root/'request.json'
        self.settings_override=override_settings(CRM_RECOVERY_STATE=self.state,CRM_RECOVERY_REQUEST=self.request)
        self.settings_override.enable();self.addCleanup(self.settings_override.disable)
        self.admin=get_user_model().objects.create_superuser('backup-admin','admin@example.test','test-password')
        self.client.force_login(self.admin)

    def test_admin_only_post_csrf_and_fixed_request(self):
        self.assertEqual(self.client.get('/management/backups/').status_code,200)
        self.assertEqual(self.client.get('/management/backups/start/').status_code,405)
        self.assertEqual(self.client.post('/management/backups/start/',{'kind':'full'}).status_code,503)
        (self.state/'installed').touch()
        self.assertEqual(self.client.post('/management/backups/start/',{'kind':'../../secret'}).status_code,400)
        self.assertEqual(self.client.post('/management/backups/start/',{'kind':'full'}).status_code,302)
        payload=json.loads(self.request.read_text());self.assertEqual(payload['kind'],'full')
        self.assertEqual(str(uuid.UUID(payload['request_id'])),payload['request_id'])
        self.assertNotIn('path',payload)
        self.assertEqual(self.request.stat().st_mode & 0o777,0o600)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post('/management/backups/start/',{'kind':'full'}).status_code,403)
        staff=get_user_model().objects.create_user('backup-staff',is_staff=True)
        self.client.force_login(staff)
        for path in ['/management/backups/','/management/backups/status/']:
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post('/management/backups/start/',{'kind':'full'}).status_code,403)

    def test_download_is_private_bound_to_completed_id_and_preserved_after_failure(self):
        request_id=str(uuid.uuid4());filename=request_id+'.sqlite3'
        (self.state/'downloads'/filename).write_bytes(b'fictional backup')
        last={'request_id':request_id,'filename':filename,'kind':'database'}
        (self.state/'status.json').write_text(json.dumps({'state':'failed','last_success':last}))
        url='/management/backups/download/'+request_id+'/'
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(b''.join(response.streaming_content),b'fictional backup')
        self.assertIn('no-store',response['Cache-Control'])
        response.close()
        self.assertEqual(self.client.get('/management/backups/download/'+str(uuid.uuid4())+'/').status_code,404)
        (self.state/'downloads'/filename).unlink();(self.state/'downloads'/filename).symlink_to(self.request)
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.logout();self.assertEqual(self.client.get(url).status_code,302)

    def test_stale_worker_status_does_not_lock_web_buttons_forever(self):
        (self.state/'status.json').write_text(json.dumps({'state':'running','started':'2020-01-01T00:00:00+00:00'}))
        data=self.client.get('/management/backups/status/').json()
        self.assertFalse(data['manual']['busy'])
        self.assertEqual(data['manual']['state'],'failed')


class RecoveryWorkerTests(SimpleTestCase):
    def load_worker(self):
        import importlib.util
        import sys
        from . import recovery
        with patch.dict(sys.modules, {'crm_recovery': recovery}):
            spec=importlib.util.spec_from_file_location('test_recovery_worker',Path(__file__).resolve().parent.parent/'deploy/recovery-worker.py')
            worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        return worker

    def test_manual_worker_publishes_verified_download_and_keeps_previous_on_failure(self):
        import builtins
        worker=self.load_worker()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state';state.mkdir();(state/'downloads').mkdir()
            source=root/'source.sqlite3';database(source)
            request=root/'request.json';request_id=str(uuid.uuid4())
            request.write_text(json.dumps({'kind':'database','request_id':request_id}))
            original_open=builtins.open
            def open_lock(path,*args,**kwargs):
                if str(path).startswith('/run/'):
                    path=root/Path(path).name
                return original_open(path,*args,**kwargs)
            with patch.multiple(worker,STATE=state,REQUEST=request,DATABASE=source),patch.object(worker.os,'geteuid',return_value=0),patch.object(worker.os,'chown'),patch.object(worker.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=0)),patch('builtins.open',side_effect=open_lock),patch.object(worker.os,'umask'):
                worker.main('manual')
                saved=json.loads((state/'status.json').read_text())
                self.assertEqual(saved['state'],'ready');self.assertEqual(saved['last_success']['request_id'],request_id)
                target=state/'downloads'/saved['filename'];self.assertTrue(target.is_file())
                self.assertEqual(digest(target),saved['sha256'])
                self.assertFalse(request.exists())
                request.write_text(json.dumps({'kind':'database','request_id':str(uuid.uuid4())}))
                with patch.object(worker,'snapshot',side_effect=OSError('fictional secret must not be logged')):
                    with self.assertRaises(SystemExit):worker.main('manual')
                failed=json.loads((state/'status.json').read_text())
                self.assertEqual(failed['state'],'failed');self.assertTrue(target.is_file())
                self.assertEqual(failed['last_success']['request_id'],request_id)
                self.assertNotIn('fictional secret',json.dumps(failed))

    def test_worker_rejects_symlink_oversize_and_unknown_requests(self):
        worker=self.load_worker()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);request=root/'request.json'
            with patch.object(worker,'REQUEST',request):
                request.write_text(json.dumps({'kind':'shell','request_id':str(uuid.uuid4())}))
                with self.assertRaises(ValueError):worker.read_request()
                request.write_text('x'*2048)
                with self.assertRaises(ValueError):worker.read_request()
                request.unlink();request.symlink_to(root/'other')
                with self.assertRaises(OSError):worker.read_request()
