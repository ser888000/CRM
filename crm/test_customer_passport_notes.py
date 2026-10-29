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

    def test_name_before_birthday_without_birth_marker(self):
        text = 'Тестов Иван Иванович ' + NOTE.replace(' г.р.', '').replace(', выдан', ' выдан')
        fields, reason = extract(text)
        self.assertFalse(reason)
        self.assertEqual(fields, extract(NOTE)[0])
        self.assertNotIn('name', fields)

    def test_birthday_without_marker_or_name(self):
        self.assertEqual(extract(NOTE.replace(' г.р.', ''))[0], extract(NOTE)[0])

    def test_ambiguous_invalid_incomplete(self):
        for text in (NOTE + '\n' + NOTE, NOTE.replace('01.02.1985', '31.02.1985'), NOTE.replace('17.07.2020', '17.07.1980')):
            with self.subTest(text=text):
                fields, reason = extract(text)
                self.assertFalse(fields)
                self.assertTrue(reason)

    def test_six_legacy_layouts(self):
        examples = [
            ('Тестов Иван Иванович 01.02.1985, паспорт 0000000001 выдан 17.07.2020 Отделением УФМС России по Тестовому округу в городе Тестовом, код подр. 000001', '000-001'),
            ('Тестов Иван Иванович 01.02.1985 паспорт 0000 000001 выдан 17.07.2020 отделением ОУФМС России по Тестовой области 000-001', '000-001'),
            ('Тестова Анна Ивановна 01.02.1985 0000 000001 УВД Тестового района РОВД 17.07.2020 17.07.2020', None),
            ('Тестов Иван Иванович\n01.02.1985 г.р., паспорт 0000 000001, выдан 17.07.2020 Тестовым РОВД Тестового УВД код подр. 000001', '000-001'),
            ('ТЕСТОВА АННА 01.02.1985, паспорт 0000000001 выдан 17.07.2020 УМВ РОССИИ ПО ТЕСТОВОЙ ОБЛАСТИ, код подр. 000-001', '000-001'),
            ('Тестова Анна Ивановна 01.02.1985, паспорт 0000 00 0001 выдан 17.07.2020 Отделом УФМС России по Тестовому округу, код подр. 000-001', '000-001'),
        ]
        for text, code in examples:
            with self.subTest(text=text):
                fields, reason = extract(text)
                self.assertFalse(reason)
                self.assertEqual(fields['passport_number'], '0000000001')
                self.assertEqual(fields['birthday'], date(1985, 2, 1))
                self.assertEqual(fields['passport_issued'], date(2020, 7, 17))
                self.assertEqual(fields.get('passport_code'), code)
                self.assertNotIn('17.07.2020', fields['passport_issued_by'])

    def test_missing_code_does_not_invent_or_clear_it(self):
        customer = Customer(name='Тест', passport=NOTE.replace('код подр. 000-001.', ''), passport_code='123-456')
        updates, reason = plan(customer)
        self.assertFalse(reason)
        self.assertNotIn('passport_code', updates)
        self.assertEqual(updates['passport_number'], '0000000001')

    def test_conflicting_issue_dates_and_malformed_numbers_are_rejected(self):
        examples = [NOTE.replace('0000 000001', '00000000011'), NOTE.replace('0000 000001', '000000001'),
                    NOTE.replace('17.07.2020', '17.07.2020 18.07.2020'),
                    NOTE.replace('000-001', '000-01'), NOTE + ' ' + NOTE]
        for text in examples:
            with self.subTest(text=text):
                fields, reason = extract(text)
                self.assertFalse(fields)
                self.assertTrue(reason)

    def test_trailing_notes_and_equivalent_existing_code(self):
        fields, reason = extract(NOTE + ' Дополнительная пометка от менеджера.')
        self.assertFalse(reason)
        self.assertEqual(fields, extract(NOTE)[0])
        customer = Customer(name='Тест', passport=NOTE, passport_code='000001')
        updates, reason = plan(customer)
        self.assertFalse(reason)
        self.assertNotIn('passport_code', updates)

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

    def test_new_format_fills_only_empty_fields_preserving_customer_name(self):
        note = 'Тестов Иван Иванович ' + NOTE.replace(' г.р.', '')
        Customer.objects.filter(pk=self.customer.pk).update(passport=note, birthday=date(1985, 2, 1))
        with patch('crm.customer_passport_notes_views.backup', return_value=Path('test.sqlite3')):
            self.assertContains(self.client.post(self.url), 'Обновлено заказчиков: 1')
            self.assertContains(self.client.post(self.url), 'Обновлено заказчиков: 0')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, 'Тест')
        self.assertEqual(self.customer.passport, note)
        self.assertEqual(self.customer.birthday, date(1985, 2, 1))
        self.assertEqual(self.customer.passport_number, '0000000001')
