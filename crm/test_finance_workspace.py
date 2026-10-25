from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase,Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from .models import Customer,Operator,Contract,Payment,PaymentMethod,AuditEvent

class FinanceWorkspaceTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','test@example.test','test-password');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Петров Иван');self.other=Customer.objects.create(name='Другой')
        self.operator=Operator.objects.create(name='Тестовый ТО');self.method=PaymentMethod.objects.create(name='Карта')
        self.contract=Contract.objects.create(customer=self.customer,operator=self.operator,number='100')
        self.second=Contract.objects.create(customer=self.other,operator=self.operator,number='200')
        self.payments=[]
        for kind,amount in [('customer','1000'),('customer_refund','100'),('operator','800'),('operator_refund','50')]:
            self.payments.append(Payment.objects.create(contract=self.contract,kind=kind,amount=amount,method=self.method,date=date(2026,10,25),notes='Тестовая операция'))
    def test_columns_multiselect_totals_and_numeric_sort(self):
        r=self.client.get('/finances/',{'f_kind':['Поступление от клиента','Возврат от ТО'],'sort':'-incoming'})
        self.assertEqual([p.kind for p in r.context['rows']],['customer','operator_refund'])
        self.assertEqual(r.context['count'],2);self.assertEqual(r.context['incoming'],Decimal('1050'));self.assertEqual(r.context['outgoing'],0)
        self.assertContains(r,'Фильтр: Примечание');self.assertContains(r,'1 050,00')
        self.assertEqual(next(c['text'] for c in r.context['footer'] if c['key']=='incoming'),'1 050,00')
    def test_unicode_search_dates_session_and_reset(self):
        r=self.client.get('/finances/',{'customer':'пЕтРоВ','operator':'тестовый','start':'2026-10-25','end':'2026-10-25'})
        self.assertEqual(r.context['count'],4)
        self.assertEqual(self.client.get('/finances/',follow=True).context['count'],4)
        with patch('crm.finance_views.timezone.localdate',return_value=date(2026,11,1)):
            self.assertEqual(self.client.get('/finances/?period=today').context['count'],0)
            self.assertEqual(self.client.get('/finances/?period=month').context['count'],0)
        response=self.client.get('/finances/?reset=1',follow=True)
        self.assertEqual(response.context['count'],0);self.assertEqual(response.context['start_value'],'2026-11-01')
        for query in ('start=bad','start=2026-11-01&end=2026-10-01'):
            r=self.client.get('/finances/?'+query);self.assertFalse(r.context['dateform'].is_valid());self.assertEqual(r.context['count'],0)
    def test_totals_include_all_pages(self):
        Payment.objects.bulk_create([Payment(contract=self.contract,kind='customer',amount=1,method=self.method) for _ in range(101)])
        r=self.client.get('/finances/?page=2')
        self.assertEqual(r.context['count'],105);self.assertEqual(len(r.context['rows']),5)
        self.assertEqual(r.context['incoming'],Decimal('1151'));self.assertIn('page=2',r.context['return_query'])
    def payment_data(self,**kwargs):
        return {'contract':self.contract.pk,'customer':self.customer.pk,'date':'2026-10-25','kind':'customer','amount':'1 234,56','method':self.method.pk,'currency':'RUB','notes':'Записано через карточку',**kwargs}
    def test_create_edit_and_contract_totals(self):
        self.assertContains(self.client.get('/finances/new/'),'data-contracts-url="/finances/contracts/"')
        r=self.client.post('/finances/new/',self.payment_data(return_query='customer=Петров&sort=-date&next=https://example.test'))
        self.assertEqual(r.status_code,302);self.assertNotIn('next=',r.url)
        p=Payment.objects.get(notes='Записано через карточку');self.assertEqual(p.amount,Decimal('1234.56'))
        version=self.client.get(f'/finances/{p.pk}/').context['form']['version'].value()
        r=self.client.post(f'/finances/{p.pk}/',self.payment_data(amount='2 000,00',version=version))
        self.assertEqual(r.status_code,302);p.refresh_from_db();self.assertEqual(p.amount,2000)
        self.assertEqual(AuditEvent.objects.filter(object_type='crm.Payment',object_id=str(p.pk)).count(),2)
        self.assertEqual(self.contract.paid,2900)
    def test_stale_edits_mismatch_and_negative_amount_rejected(self):
        p=self.payments[0];version=self.client.get(f'/finances/{p.pk}/').context['form']['version'].value()
        p.amount=900;p.save()
        r=self.client.post(f'/finances/{p.pk}/',self.payment_data(version=version))
        self.assertContains(r,'изменена в другом окне');p.refresh_from_db();self.assertEqual(p.amount,900)
        for data in (self.payment_data(customer=self.other.pk),self.payment_data(amount='-1')):
            r=self.client.post('/finances/new/',data);self.assertEqual(r.status_code,200)
        self.assertEqual(Payment.objects.count(),4)
    def test_customer_contract_endpoint_and_view_only_permissions(self):
        response=self.client.get('/finances/contracts/',{'customer':self.customer.pk})
        self.assertEqual([v['id'] for v in response.json()['contracts']],[self.contract.pk])
        viewer=get_user_model().objects.create_user('viewer');viewer.user_permissions.add(Permission.objects.get(codename='view_payment'));self.client.force_login(viewer)
        r=self.client.get('/finances/?kind=customer');self.assertEqual(r.status_code,200);self.assertNotContains(r,'+ Финансовая операция')
        for url in ('/finances/new/',f'/finances/{self.payments[0].pk}/','/finances/contracts/'):
            self.assertEqual(self.client.get(url).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post('/finances/new/',self.payment_data()).status_code,403)
