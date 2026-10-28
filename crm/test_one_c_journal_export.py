from datetime import date
from xml.etree import ElementTree as ET
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase
from .models import Customer, Operator, Contract, ContractLine, Payment, PaymentMethod


class JournalOneCExportTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Тестовый Заказчик')
        self.operator = Operator.objects.create(name='Тестовый ТО')
        self.card = PaymentMethod.objects.create(name='Тинькофф Интернет')
        self.cash = PaymentMethod.objects.create(name='Касса наличные')
        self.admin = get_user_model().objects.create_superuser('journal-export-admin', '', 'test')
        self.url = '/contracts/export/1c/'

    def contract(self, number, method=None, day=1):
        contract = Contract.objects.create(number=number, date=date(2026, 1, day),
            customer=self.customer, operator=self.operator, payment_method=method or self.card)
        ContractLine.objects.create(contract=contract, amount=100000)
        return contract

    def test_exact_journal_column_and_header_filters_over_twenty_download_xml_only(self):
        wanted = [self.contract(f'KEEP-{n}', day=2) for n in range(23)]
        self.contract('OTHER', day=3)
        self.contract('KEEP-CASH', self.cash, day=2)
        params = {'period': 'custom', 'start': '2026-01-01', 'end': '2026-01-31',
                  'f_date': ['02.01.2026'], 'f_payment_method': ['Тинькофф Интернет'], 'sort': 'number'}
        self.client.force_login(self.admin)
        journal = self.client.get('/', params)
        expected = {str(c.exchange_id) for c in journal.context['rows']}
        self.assertEqual(expected, {str(c.exchange_id) for c in wanted})
        preview = self.client.get(self.url, params)
        self.assertEqual(preview.context['journal_count'], 23)
        from urllib.parse import urlencode
        response = self.client.post(self.url + '?' + urlencode(params, doseq=True), {'exchange_year': 2026})
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
        self.assertIn('no-store', response['Cache-Control'])
        root = ET.fromstring(response.content)
        self.assertEqual({c.get('ID') for c in root.findall('CONTRACT')}, expected)
        self.assertEqual({c.get('VOUCHER_DATE') for c in root.findall('CONTRACT')}, {'2026-12-31'})
        self.assertNotIn('zip', response['Content-Type'])

    def test_warnings_link_to_exact_contract_in_new_tab(self):
        contract = self.contract('WARNING')
        self.client.force_login(self.admin)
        response = self.client.get(self.url + '?start=2026-01-01&end=2026-01-31')
        self.assertContains(response, f'href="/contracts/{contract.pk}/" target="_blank" rel="noopener"')

    def test_permissions_allow_accountant_but_deny_staff_and_direct_post(self):
        self.contract('ROLE')
        viewer = get_user_model().objects.create_user('viewer', is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename='view_contract', content_type__app_label='crm'))
        self.client.force_login(viewer)
        self.assertNotContains(self.client.get('/?start=2026-01-01&end=2026-01-31'), 'Выгрузка в 1С')
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'exchange_year': 2026}).status_code, 403)
        accountant = get_user_model().objects.create_user('bookkeeper')
        accountant.groups.add(Group.objects.get(name='Бухгалтер'))
        self.client.force_login(accountant)
        self.assertContains(self.client.get('/?start=2026-01-01&end=2026-01-31'), 'Выгрузка в 1С')
        self.assertEqual(self.client.get(self.url + '?start=2026-01-01&end=2026-01-31').status_code, 200)
        csrf = Client(enforce_csrf_checks=True); csrf.force_login(accountant)
        self.assertEqual(csrf.post(self.url, {'exchange_year': 2026}).status_code, 403)

    def test_empty_invalid_dates_and_no_business_writes(self):
        self.contract('READONLY')
        self.client.force_login(self.admin)
        counts = (Contract.objects.count(), Payment.objects.count(), Customer.objects.count())
        for query in ('start=2027-01-01&end=2027-02-01', 'start=bad&end=2026-01-01'):
            response = self.client.post(self.url + '?' + query, {'exchange_year': 2026})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('application/xml', response['Content-Type'])
        self.assertEqual(counts, (Contract.objects.count(), Payment.objects.count(), Customer.objects.count()))

    def test_header_search_ignores_dates_like_journal_and_ids_cannot_override_filters(self):
        wanted = self.contract('FIND')
        self.contract('OTHER')
        self.client.force_login(self.admin)
        response = self.client.post(self.url + '?number=FIND&start=2026-12-01&end=2026-12-31',
                                    {'exchange_year': 2026, 'contracts': ['9999']})
        root = ET.fromstring(response.content)
        self.assertEqual([c.get('ID') for c in root.findall('CONTRACT')], [str(wanted.exchange_id)])

    def test_saved_filters_and_cash_only_empty_export(self):
        wanted = self.contract('SAVED')
        self.contract('OTHER')
        cash = self.contract('CASH', self.cash)
        self.client.force_login(self.admin)
        session = self.client.session
        session['contract_journal'] = 'number=SAVED&start=2026-01-01&end=2026-01-31'
        session.save()
        preview = self.client.get(self.url)
        self.assertEqual(preview.context['journal_count'], 1)
        response = self.client.post(self.url, {'exchange_year': 2026})
        root = ET.fromstring(response.content)
        self.assertEqual([c.get('ID') for c in root.findall('CONTRACT')], [str(wanted.exchange_id)])
        empty = self.client.post(self.url + '?number=CASH&start=2026-01-01&end=2026-01-31',
                                 {'exchange_year': 2026})
        self.assertEqual(empty.context['export_count'], 0)
        self.assertFalse(empty.context['ready'])
        self.assertNotIn('application/xml', empty['Content-Type'])
