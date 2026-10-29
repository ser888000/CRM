import importlib.util
import json
import os
import sqlite3
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import SimpleTestCase
from .backup_retention import prune_backups, ROOT_PATTERN


class RetentionTests(SimpleTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def make(self, number, valid=True):
        path = self.folder / f'20261029-{number:06}.sqlite3'
        if valid:
            with sqlite3.connect(path) as db:db.execute('CREATE TABLE example (value INTEGER)')
        else:path.write_text('incomplete')
        os.utime(path, (number, number))
        return path

    def test_keep_latest_valid_and_ignore_unrelated_and_links(self):
        old = self.make(1); latest = self.make(2)
        unrelated = self.folder/'manual.sqlite3'; unrelated.write_text('keep')
        link = self.folder/'20261029-000003.sqlite3'; link.symlink_to(latest)
        self.assertGreater(prune_backups(self.folder, ROOT_PATTERN), 0)
        self.assertFalse(old.exists()); self.assertTrue(latest.exists())
        self.assertTrue(unrelated.exists()); self.assertTrue(link.is_symlink())

    def test_failed_new_backup_keeps_last_good_one(self):
        oldest = self.make(1); good = self.make(2); broken = self.make(3, valid=False)
        prune_backups(self.folder, ROOT_PATTERN)
        self.assertFalse(oldest.exists()); self.assertTrue(good.exists()); self.assertTrue(broken.exists())

    def test_no_verified_backup_deletes_nothing(self):
        first = self.make(1, valid=False); second = self.make(2, valid=False)
        self.assertEqual(prune_backups(self.folder, ROOT_PATTERN), 0)
        self.assertTrue(first.exists()); self.assertTrue(second.exists())

    def test_empty_file_is_not_a_verified_backup(self):
        good = self.make(1)
        empty = self.folder/'20261029-000002.sqlite3'; empty.touch(); os.utime(empty,(2,2))
        prune_backups(self.folder, ROOT_PATTERN)
        self.assertTrue(good.exists()); self.assertTrue(empty.exists())

    def test_protected_rollback_copy_is_kept(self):
        protected = self.make(1); latest = self.make(2)
        prune_backups(self.folder, ROOT_PATTERN, protected=[protected])
        self.assertTrue(protected.exists()); self.assertTrue(latest.exists())

    def test_cleanup_removes_completed_job_files_only(self):
        spec = importlib.util.spec_from_file_location('cleanup_storage', Path(__file__).resolve().parent.parent/'deploy/cleanup-storage.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        jobs = []
        for state in ('completed','failed','running','queued'):
            job=self.folder/str(uuid.uuid4()); job.mkdir()
            (job/'status.json').write_text(json.dumps({'state':state}))
            (job/'package.zip').write_text('synthetic'); jobs.append(job)
        module.cleanup_legacy(self.folder)
        self.assertFalse(jobs[0].exists()); self.assertFalse(jobs[1].exists())
        self.assertTrue(jobs[2].exists()); self.assertTrue(jobs[3].exists())
