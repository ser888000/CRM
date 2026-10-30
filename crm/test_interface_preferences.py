import json
from datetime import date
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase,Client
from django.urls import reverse
from .models import UserInterfacePreference,Customer,Operator,Contract,ContractLine,Payment,Task,PaymentMethod


class InterfaceTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('ui-test',password='synthetic-only')
        self.other=get_user_model().objects.create_superuser('ui-other',password='synthetic-only')
        self.client.force_login(self.user);self.url=reverse('interface_preferences')
    def post(self,data):return self.client.post(self.url,json.dumps(data),content_type='application/json')
    def test_theme_and_widths_follow_user_between_browsers(self):
        self.assertEqual(self.client.get(self.url).json()['theme'],'accounting')
        self.assertEqual(self.post({'theme':'spreadsheet'}).status_code,200)
        self.post({'table':'contracts','widths':{'amount':185}});self.post({'table':'contracts','widths':{'customer':245}})
        another=Client();another.force_login(self.user)
        self.assertEqual(another.get(self.url).json(),{'theme':'spreadsheet','column_widths':{'contracts':{'amount':185,'customer':245}}})
        another.force_login(self.other);self.assertEqual(another.get(self.url).json(),{'theme':'accounting','column_widths':{}})
        self.assertEqual(self.post({'table':'contracts','widths':None}).json()['column_widths'],{})
    def test_no_other_user_or_arbitrary_values_and_csrf_is_required(self):
        for data in ({'user_id':self.other.pk,'theme':'office'},{'theme':'evil'},{'table':'contracts','widths':{'amount':0}},{'table':'contracts','widths':{'amount':True}},{'table':'unknown','widths':{}},{'table':'contracts','widths':{'amount':5000}}):self.assertEqual(self.post(data).status_code,400)
        self.assertFalse(UserInterfacePreference.objects.exists())
        self.assertEqual(Client().get(self.url).status_code,302)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url,json.dumps({'theme':'office'}),content_type='application/json').status_code,403)
    def test_theme_rendered_before_scripts_and_read_only_user_can_choose(self):
        reader=get_user_model().objects.create_user('read-only');self.client.force_login(reader)
        self.assertEqual(self.post({'theme':'office'}).status_code,200)
        self.client.force_login(self.user);self.post({'theme':'spreadsheet'})
        response=self.client.get('/?period=month');self.assertContains(response,'data-theme="spreadsheet"');self.assertContains(response,'id="interface-theme"')
    def test_column_filters_and_all_numeric_totals_use_same_rows(self):
        c=Customer.objects.create(name='SYNTHETIC ONE');other=Customer.objects.create(name='SYNTHETIC TWO');op=Operator.objects.create(name='TEST OPERATOR')
        contract=Contract.objects.create(customer=c,operator=op,number='1',date=date(2026,10,1),adults=2,children=1)
        second=Contract.objects.create(customer=other,operator=op,number='2',date=date(2026,10,1),adults=4)
        ContractLine.objects.create(contract=contract,amount=100);ContractLine.objects.create(contract=second,amount=500)
        method=PaymentMethod.objects.create(name='TEST METHOD')
        Payment.objects.create(method=method,contract=contract,kind='customer',amount=80,date=date(2026,10,1),rate=90)
        Payment.objects.create(method=method,contract=contract,kind='operator',amount=60,date=date(2026,10,1),rate=100)
        Task.objects.create(contract=contract,title='SYNTHETIC TASK ONE',due=date(2026,10,1))
        Task.objects.create(contract=second,title='SYNTHETIC TASK TWO',due=date(2026,10,1))
        params={'start':'2026-10-01','end':'2026-10-31','q_customer':'ONE'}
        result=self.client.get('/',params);self.assertEqual(result.context['count'],1)
        self.assertEqual(result.context['totals'],{'amount':Decimal(100),'paid':Decimal(80),'debt':Decimal(20),'cost':Decimal(60),'profit':Decimal(40),'adults':2,'children':1})
        self.assertContains(result,'name="q_customer" value="ONE"')
        result=self.client.get('/finances/',params);self.assertEqual(result.context['count'],2)
        footer={c['key']:c['text'] for c in result.context['footer']};self.assertEqual(footer['incoming'],'80,00');self.assertEqual(footer['outgoing'],'60,00');self.assertEqual(footer['rate'],'Ср. 95,00')
        result=self.client.get('/customers/',{'q_name':'ONE'});self.assertEqual(result.context['count'],1);self.assertEqual(result.context['contract_total'],1)
        result=self.client.get('/tasks/',{'period':'all','q_title':'ONE'});self.assertEqual(result.context['count'],1);self.assertEqual(len(result.context['rows']),1)
