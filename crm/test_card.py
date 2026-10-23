from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from .models import Customer,Operator,Contract,ContractLine,Payment,PaymentMethod,Task,AuditEvent,Tourist

class CardTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123')
        self.client.force_login(self.user)
        self.c=Contract.objects.create(customer=Customer.objects.create(name='Тестовый заказчик'),operator=Operator.objects.create(name='Тестовый ТО'))
        self.method=PaymentMethod.objects.create(name='Карта')
        ContractLine.objects.create(contract=self.c,description='Стоимость',amount=200000)
        self.url=f'/contracts/{self.c.pk}/'
    def test_sections_and_new_card_render(self):
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,200)
        for text in ['200 000,00','Заказчик','Туристы и стоимость','Брони ТО','Финансы','Задачи','История','Выйти без сохранения']:
            self.assertContains(response,text)
        self.assertContains(response,'crm/contract_card.js')
        self.assertEqual(self.client.get('/contracts/new/').status_code,200)
    def test_create_manual_and_update_stale_guard(self):
        data={'action':'contract','customer':self.c.customer_id,'operator':self.c.operator_id,'date':'2026-10-23','source_currency':'RUB','adults':0,'children':0,'infants':0,'notes':'Пример'}
        response=self.client.post('/contracts/new/',data)
        self.assertEqual(response.status_code,302)
        created=Contract.objects.exclude(pk=self.c.pk).get()
        self.assertEqual(created.notes,'Пример')
        data['version']=str(created.updated_at);data['notes']='Правка'
        response=self.client.post(f'/contracts/{created.pk}/',data)
        self.assertEqual(response.status_code,302)
        response=self.client.post(f'/contracts/{created.pk}/',data)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Договор изменился')
    def test_add_and_edit_payment_inside_card(self):
        data={'action':'payment','payment-new-date':'2026-10-23','payment-new-kind':'customer','payment-new-amount':'50 000,00','payment-new-method':self.method.pk}
        self.assertEqual(self.client.post(self.url,data).status_code,302)
        p=Payment.objects.get();self.assertEqual(p.contract,self.c);self.assertEqual(self.c.paid,50000)
        data={'action':'payment','entry_id':p.pk,f'payment-{p.pk}-date':'2026-10-23',f'payment-{p.pk}-kind':'customer',f'payment-{p.pk}-amount':'60 000,00',f'payment-{p.pk}-method':self.method.pk}
        self.assertEqual(self.client.post(self.url,data).status_code,302)
        self.assertEqual(self.c.paid,60000)
        self.assertEqual(AuditEvent.objects.filter(object_type='crm.Payment').count(),2)
        response=self.client.get(self.url+'?tab=finance')
        self.assertContains(response,f'id="id_payment-{p.pk}-amount"')
        self.assertContains(response,'id="id_payment-new-amount"')
    def test_cross_contract_payment_rejected(self):
        other=Contract.objects.create(customer=self.c.customer,operator=self.c.operator)
        p=Payment.objects.create(contract=other,kind='customer',amount=100,method=self.method)
        self.assertEqual(self.client.post(self.url,{'action':'payment','entry_id':p.pk}).status_code,404)
    def test_permissions_and_readonly_identifiers(self):
        self.c.tourvisor_id='2193761';self.c.number='2193761';self.c.save()
        r=self.client.get(self.url)
        self.assertContains(r,'name="number" value="2193761"')
        self.assertTrue(r.context['form'].fields['number'].disabled)
        limited=get_user_model().objects.create_user('viewer',password='test-password-123')
        limited.user_permissions.add(Permission.objects.get(codename='view_contract'))
        self.client.force_login(limited)
        r=self.client.get(self.url)
        self.assertEqual(r.status_code,200)
        self.assertNotContains(r,'data-panel="finance"')
        self.assertEqual(self.client.post(self.url,{'action':'payment'}).status_code,403)
        self.assertEqual(self.client.post(self.url,{'action':'contract'}).status_code,403)
    def test_task_and_tourist_actions(self):
        response=self.client.post(self.url,{'action':'task','task-new-title':'Документы','task-new-due':'2026-11-01'})
        self.assertEqual(response.status_code,302)
        t=Task.objects.get();self.assertEqual(t.customer_id,self.c.customer_id)
        response=self.client.post(self.url,{'action':'tourist','tourist-new-name':'EXAMPLE TEST'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.c.lines.filter(tourist__name='EXAMPLE TEST').exists())
    def test_invalid_payment_stays_in_finance_and_preserves_data(self):
        response=self.client.post(self.url,{'action':'payment','payment-new-amount':'bad'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['active_tab'],'finance')
        self.assertTrue(response.context['payment_form'].errors)
        self.assertFalse(Payment.objects.exists())

    def test_copy_from_card_does_not_copy_payments(self):
        Payment.objects.create(contract=self.c,kind='customer',amount=1000,method=self.method)
        response=self.client.post(self.url,{'action':'copy'})
        self.assertEqual(response.status_code,302)
        copied=Contract.objects.exclude(pk=self.c.pk).get()
        self.assertEqual(copied.amount,Decimal('200000'))
        self.assertEqual(copied.paid,0)
        self.assertIsNone(copied.tourvisor_id)
    def test_customer_save_and_history_include_changes(self):
        response=self.client.post(self.url,{'action':'customer','customer-name':'Новое имя','customer-main_phone':'+7 000 000-00-00'})
        self.assertEqual(response.status_code,302)
        self.c.customer.refresh_from_db()
        self.assertEqual(self.c.customer.name,'Новое имя')
        response=self.client.get(self.url+'?tab=history')
        self.assertContains(response,'Данные заказчика изменены')
        self.assertContains(response,'Тестовый заказчик')
        self.assertContains(response,'Новое имя')
