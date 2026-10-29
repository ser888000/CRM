from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from .customer_passport_notes import extract, plan
from .customer_passport_notes_views import backup
from .models import Customer, AuditEvent

NOTE = '01.02.1985 г.р., паспорт 0000 000001, выдан 17.07.2020 ГУ МВД РОССИИ ПО ТЕСТОВОЙ ОБЛАСТИ код подр. 000-001.'


class ParserTests(SimpleTestCase):
    def test_complete_record(self):
        fields, reason = extract(NOTE)
        self.assertFalse(reason)
        self.assertEqual(fields['passport_number'], '0000000001')
        self.assertEqual(fields['birthday'], date(1985, 2, 1))
        self.assertEqual(fields['passport_issued_by'], 'ГУ МВД РОССИИ ПО ТЕСТОВОЙ ОБЛАСТИ')
        self.assertEqual(fields['passport_code'], '000-001')

    def test_ambiguous_invalid_incomplete(self):
        for text in (NOTE + '\n' + NOTE, NOTE.replace('01.02.1985', '31.02.1985'), NOTE.replace('код подр. 000-001.', ''), NOTE.replace('17.07.2020', '17.07.1980')):
            with self.subTest(text=text):
                fields, reason = extract(text)
                self.assertFalse(fields)
                self.assertTrue(reason)

    def test_existing_and_foreign_passports_are_preserved(self):
        customer = Customer(name='Тест', passport=NOTE, passport_number='9999999999')
        self.assertFalse(plan(customer)[0])
        customer.passport_number = ''; customer.passport_type = '0'
        self.assertFalse(plan(customer)[0])

    def test_backup_is_complete_private_and_checked(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'crm.sqlite3'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE example(value TEXT)')
                db.execute("INSERT INTO example VALUES ('before')")
            with override_settings(DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(source)}}):
                result = backup()
            self.assertEqual(result.stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(result) as db:
                self.assertEqual(db.execute('SELECT value FROM example').fetchone(), ('before',))


class ImportTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('admin', password='test')
        self.customer = Customer.objects.create(name='Тест', passport=NOTE)
        self.url = reverse('customer_passport_notes')
        self.client.force_login(self.admin)

    def test_get_readonly_post_fills_and_repeat_is_idempotent(self):
        with patch('crm.customer_passport_notes_views.backup', return_value=Path('test.sqlite3')) as mocked:
            self.assertEqual(self.client.get(self.url).status_code, 200)
            mocked.assert_not_called()
            response = self.client.post(self.url)
            mocked.assert_called_once()
            self.assertContains(response, 'Обновлено заказчиков: 1')
            self.customer.refresh_from_db()
            self.assertEqual(self.customer.passport, NOTE)
            self.assertEqual(self.customer.passport_number, '0000000001')
            self.assertEqual(AuditEvent.objects.filter(action='passport_from_notes').count(), 1)
            self.assertContains(self.client.post(self.url), 'Обновлено заказчиков: 0')
            self.assertEqual(AuditEvent.objects.filter(action='passport_from_notes').count(), 1)

    def test_backup_failure_prevents_all_writes(self):
        with patch('crm.customer_passport_notes_views.backup', side_effect=OSError):
            self.assertContains(self.client.post(self.url), 'Изменения не применены')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.passport_number, '')
        self.assertFalse(AuditEvent.objects.exists())

    def test_admin_only_and_invalid_backup_token(self):
        self.assertEqual(self.client.get(reverse('customer_passport_notes_backup', args=['invalid'])).status_code, 404)
        user = get_user_model().objects.create_user('employee')
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse('customer_passport_notes_backup', args=['invalid'])).status_code, 403)

    def test_conflicting_and_multiple_records_are_unchanged(self):
        Customer.objects.filter(pk=self.customer.pk).update(passport_number='9999999999')
        other = Customer.objects.create(name='Другой тест', passport=NOTE + '\n' + NOTE)
        with patch('crm.customer_passport_notes_views.backup', return_value=Path('test.sqlite3')):
            response = self.client.post(self.url)
        self.assertContains(response, 'Для проверки: 2')
        self.customer.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(self.customer.passport_number, '9999999999')
        self.assertIsNone(self.customer.birthday)
        self.assertEqual(other.passport_number, '')

    def test_post_requires_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url).status_code, 403)

    def test_permission_error_identifies_backup_stage_without_private_paths(self):
        with patch('crm.customer_passport_notes_views.backup', side_effect=PermissionError(13, 'SECRET PATH')):
            response = self.client.post(self.url)
        self.assertContains(response, 'Создание и проверка резервной копии: Нет прав')
        self.assertNotContains(response, 'SECRET PATH')

    def test_database_failure_rolls_back_and_keeps_backup_link(self):
        from django.db import OperationalError
        with patch('crm.customer_passport_notes_views.backup', return_value=Path('test.sqlite3')), patch('crm.customer_passport_notes_views.AuditEvent.objects.create', side_effect=OperationalError('SECRET SQL')):
            response = self.client.post(self.url)
        self.assertContains(response, 'Заполнение паспортных полей: Код: OperationalError')
        self.assertContains(response, 'Резервная копия сохранена')
        self.assertNotContains(response, 'SECRET SQL')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.passport_number, '')
