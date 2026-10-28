import tempfile
from pathlib import Path
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from . import models as m
from .legacy_history import apply_history, load_history
from .test_legacy_history import fixture, package
from .legacy_history_jobs import job_folder, write_json, read_json, run_job
from .legacy_reset import clear_history


class TrainingCleanupTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('cleanup-admin', '', 'test')
        apply_history(load_history(package(fixture())))

    def test_cleanup_preserves_whole_exception_set_and_login(self):
        library = m.LibraryEntry.objects.create(title='Keep', body='Library text')
        kind = m.TaskType.objects.create(name='Template type')
        template = m.TaskTemplate.objects.create(name='Keep template', task_type=kind, anchor='start')
        preserved = [m.LibraryEntry, m.Currency, m.DepartureCity, m.Country, m.PaymentOperation, m.TaskTemplate]
        before = {model: list(model.objects.values()) for model in preserved}
        clear_history(self.admin)
        for model in (m.Contract, m.Customer, m.Task, m.Payment, m.Tourist, m.Operator, m.PaymentMethod):
            self.assertFalse(model.objects.exists(), model._meta.label)
        for model in preserved:
            after = list(model.objects.values())
            if model is m.TaskTemplate:
                for row in before[model] + after: row.pop('task_type_id', None)
            self.assertEqual(after, before[model])
        self.assertTrue(get_user_model().objects.filter(pk=self.admin.pk, is_active=True).exists())
        self.assertTrue(m.LibraryEntry.objects.filter(pk=library.pk, body='Library text').exists())
        template.refresh_from_db()
        self.assertEqual(template.task_type.name, 'Template type')

    def test_cleanup_endpoint_requires_admin_post_and_csrf(self):
        url = '/management/legacy/clear/'
        user = get_user_model().objects.create_user('viewer')
        self.client.force_login(user)
        with patch('crm.legacy_history_views.start_job') as start:
            self.assertEqual(self.client.post(url).status_code, 403)
            start.assert_not_called()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url).status_code, 403)
        with patch('crm.legacy_history_views.start_job') as start:
            self.assertEqual(self.client.post(url).status_code, 302)
            start.assert_called_once_with(None, self.admin, clear_only=True)

    def test_worker_backs_up_before_clear_and_never_clears_on_backup_failure(self):
        key = '2ee94d53-9f96-4c53-9d69-bb1f10df7475'
        with tempfile.TemporaryDirectory() as temp, override_settings(CRM_LEGACY_IMPORT_DIR=temp):
            job = job_folder(key); job.mkdir()
            write_json(job/'meta.json', {'actor_id': self.admin.pk, 'clear_only': True})
            count = m.Contract.objects.count()
            with patch('django.db.connections.close_all'), patch('crm.legacy_history_jobs.backup_database', side_effect=OSError('disk')):
                run_job(key)
            self.assertEqual(m.Contract.objects.count(), count)
            self.assertEqual(read_json(job/'status.json')['state'], 'failed')
            def backup(folder):
                self.assertEqual(m.Contract.objects.count(), count)
                (folder/'before.sqlite3').write_bytes(b'backup placeholder')
            with patch('django.db.connections.close_all'), patch('crm.legacy_history_jobs.backup_database', side_effect=backup):
                run_job(key)
            self.assertFalse(m.Contract.objects.exists())
            self.assertEqual(read_json(job/'status.json')['state'], 'completed')
            self.assertTrue((job/'before.sqlite3').exists())
