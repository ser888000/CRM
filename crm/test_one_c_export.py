import io
import json
from datetime import date
from decimal import Decimal
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from .models import Customer, Operator, Contract, ContractLine, Payment, PaymentMethod
from .one_c_export import build_plan, package_bytes


class OneCExportTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='Тестовый Заказчик', passport_number='SECRET-PASSPORT',
            main_email='secret@example.invalid', main_phone='SECRET-PHONE', birthday=date(1980,1,1))
        self.operator = Operator.objects.create(name='Проверочный ТО')
        self.contract = self.make_contract('TEST-1')

    def make_contract(self, number):
        obj = Contract.objects.create(customer=self.customer, operator=self.operator, number=number, date=date(2026,1,1))
        ContractLine.objects.create(contract=obj, description='DO-NOT-EXPORT-TOURIST', amount=100000)
        method, _ = PaymentMethod.objects.get_or_create(name='Тинькофф р/с')
        Payment.objects.create(contract=obj, method=method, kind='operator', date=date(2026,1,1), amount=70000)
        return obj

    def pay(self, method='Тинькофф Интернет', amount=40000, kind='customer', day=10, contract=None):
        method, _ = PaymentMethod.objects.get_or_create(name=method)
        return Payment.objects.create(contract=contract or self.contract, method=method, amount=amount,
            kind=kind, date=date(2026,1,day), notes='PRIVATE-PAYMENT-NOTES')

    def test_full_commission_on_first_strict_crossing_and_no_duplicate_keys(self):
        self.pay(amount=40000, day=10)
        self.pay(amount=30000, day=15)  # equality is not sufficient
        self.pay(amount=10000, day=20)
        self.pay(amount=20000, day=25)
        plan = build_plan([self.contract.pk], 2026)
        row = plan['contracts'][0]
        self.assertEqual((row['amount'], row['cost'], row['commission']), ('100000.00', '70000.00', '30000.00'))
        self.assertEqual(row['shipment_date'], '2026-01-20')
        self.assertEqual(len(plan['operations']), 4)
        self.assertEqual(plan, build_plan([self.contract.pk], 2026))
        self.assertEqual(len({o['id'] for o in plan['operations']}), 4)

    def test_bank_is_not_exported_but_counts_and_old_contract_is_included(self):
        self.contract.date = date(2025,12,1); self.contract.save()
        self.pay(method='Счет', amount=80000)
        plan = build_plan([self.contract.pk], 2026)
        self.assertEqual(plan['operations'], [])
        self.assertEqual(plan['contracts'][0]['shipment_date'], '2026-01-10')
        self.assertEqual(plan['contracts'][0]['payments'][0]['status'], 'bank_statement_only')

    def test_refund_uses_negative_amount_and_does_not_reverse_accounts(self):
        self.pay(method='СБП', amount=100000)
        self.pay(method='СБП', amount=10000, kind='customer_refund', day=11)
        plan = build_plan([self.contract.pk], 2026)
        op = plan['operations'][1]
        self.assertEqual((op['debit'],op['credit'],op['amount']), ('57.2','62.2','-10000.00'))
        self.assertEqual(plan['contracts'][0]['shipment_status'], 'requires_review')
        self.assertIsNone(plan['contracts'][0]['shipment_date'])

    def test_cash_orders_keep_positive_document_sum_and_signed_source_in_xml(self):
        receipt = self.pay(method='Касса чек', amount=80000)
        refund = self.pay(method='Касса чек', amount=5000, kind='customer_refund', day=11)
        plan = build_plan([self.contract.pk], 2026)
        with ZipFile(io.BytesIO(package_bytes(plan))) as archive:
            root = ET.fromstring(archive.read('exchange.xml'))
        operations = root.findall('OPERATIONS/OPERATION')
        self.assertEqual(len(operations), 2)
        expected = [('cash_receipt', '50.1', '62.2', '80000.00', receipt),
                    ('cash_refund', '62.2', '50.1', '5000.00', refund)]
        for operation, (kind, debit, credit, amount, payment) in zip(operations, expected):
            self.assertEqual(tuple(operation.get(key) for key in ('TYPE', 'DEBIT', 'CREDIT', 'AMOUNT')),
                             (kind, debit, credit, amount))
            self.assertEqual(operation.get('STATUS'), 'requires_cash_analytics')
            self.assertEqual(operation.find('SOURCE_PAYMENT').get('ID'), str(payment.exchange_id))
            self.assertEqual(operation.find('PAYER').get('ID'), str(self.customer.exchange_id))
        source = root.find(f"CONTRACT/PAYMENT[@ID='{refund.exchange_id}']")
        self.assertEqual(source.get('AMOUNT'), '-5000.00')
        self.assertEqual(source.get('METHOD'), 'Касса чек')
        self.assertEqual(source.get('STATUS'), 'planned')
        # A cash refund must not invent automatic recognition/storno of commission.
        self.assertEqual(plan['contracts'][0]['shipment_status'], 'requires_review')
        self.assertEqual(plan['operations'], build_plan([self.contract.pk], 2026)['operations'])

    def test_offset_is_one_operation_with_both_contract_analytics(self):
        other = self.make_contract('TEST-2')
        source = self.pay(method='Зачет', amount=10000, kind='customer_refund')
        target = self.pay(method='Зачет', amount=10000, contract=other)
        plan = build_plan([self.contract.pk, other.pk], 2026)
        self.assertEqual(len(plan['operations']),1)
        op=plan['operations'][0]
        self.assertEqual(op['type'],'offset')
        self.assertEqual(op['debit_contract'],str(self.contract.exchange_id))
        self.assertEqual(op['credit_contract'],str(other.exchange_id))
        self.assertEqual(set(op['payments']),{str(source.exchange_id),str(target.exchange_id)})
        self.assertEqual(op['status'],'confirm_pair')
        one = build_plan([self.contract.pk],2026)
        self.assertFalse(one['operations'])
        self.assertIn('offset_counterpart_not_selected',{i['code'] for i in one['issues']})
        third = self.make_contract('TEST-3')
        self.pay(method='Зачет', amount=10000, contract=third)
        ambiguous = build_plan([self.contract.pk,other.pk],2026)
        self.assertFalse(ambiguous['operations'])  # competing row outside selected sample
        self.assertIn('ambiguous_offset',{i['code'] for i in ambiguous['issues']})

    def test_privacy_and_exact_mapping(self):
        self.pay(method='Тинькофф Интернет неизвестный',amount=80000)
        self.pay(method='Кредит',amount=1000)
        plan=build_plan([self.contract.pk],2026)
        self.assertFalse(plan['operations'])
        self.assertIn('unmapped_method',{i['code'] for i in plan['issues']})
        with ZipFile(io.BytesIO(package_bytes(plan))) as archive:
            for name in archive.namelist():
                data=archive.read(name)
                for secret in [b'SECRET-PASSPORT',b'secret@example.invalid',b'SECRET-PHONE',b'DO-NOT-EXPORT-TOURIST',b'PRIVATE-PAYMENT-NOTES']:
                    self.assertNotIn(secret,data)
            xml=ET.fromstring(archive.read('exchange.xml'))
            self.assertEqual(len(xml.findall('CONTRACT/ROW')),1)
            self.assertEqual(json.loads(archive.read('plan.json')),plan)
            self.assertIn('не XML',archive.read('README.txt').decode('utf-8-sig'))

    def test_cash_excludes_chain_and_unknown_mixed_cash_is_flagged(self):
        method=PaymentMethod.objects.create(name='Касса наличные')
        self.contract.payment_method=method;self.contract.save()
        plan=build_plan([self.contract.pk],2026)
        self.assertFalse(plan['contracts']);self.assertFalse(plan['operations'])
        self.pay(amount=100000)
        plan=build_plan([self.contract.pk],2026)
        self.assertEqual(plan['issues'][0]['code'],'cash_mixed_requires_review')

    def test_year_limits_and_previous_history_are_used(self):
        payment=self.pay(amount=80000)
        payment.date=date(2025,12,31);payment.save()
        self.pay(amount=10000)
        plan=build_plan([self.contract.pk],2026)
        self.assertEqual(len(plan['operations']),1)
        self.assertEqual(plan['contracts'][0]['shipment_status'],'outside_period')
        self.assertEqual(plan['contracts'][0]['shipment_date'],'2025-12-31')
        with self.assertRaises(ValueError):build_plan([],2026)
        with self.assertRaises(ValueError):build_plan([self.contract.pk],0)

    def test_web_access_and_download_are_read_only(self):
        self.pay()
        url='/management/1c/'
        self.assertEqual(self.client.get(url).status_code,302)
        user=get_user_model().objects.create_user('not-admin',password='test')
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code,403)
        admin=get_user_model().objects.create_superuser('export-admin','','test')
        self.client.force_login(admin)
        self.assertContains(self.client.get(url),'не подходят для штатной обработки')
        count=Payment.objects.count()
        response=self.client.post(url,{'year':2026,'contracts':[self.contract.pk]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'application/zip')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(Payment.objects.count(),count)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(admin)
        self.assertEqual(csrf.post(url,{'year':2026,'contracts':[self.contract.pk]}).status_code,403)

    def test_ids_are_distinct_between_objects_and_survive_changes(self):
        other=self.make_contract('OTHER')
        self.assertNotEqual(self.contract.exchange_id,other.exchange_id)
        key=self.contract.exchange_id
        self.contract.number='CHANGED';self.contract.save();self.contract.refresh_from_db()
        self.assertEqual(self.contract.exchange_id,key)

    def test_contract_copy_gets_new_exchange_identity(self):
        from .services import copy_contract
        copied=copy_contract(self.contract)
        self.assertNotEqual(copied.exchange_id,self.contract.exchange_id)
        self.assertNotEqual(build_plan([copied.pk],2026)['contracts'][0]['id'],str(self.contract.exchange_id))
