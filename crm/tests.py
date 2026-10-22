from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Customer,Operator,Contract,ContractLine,Payment,TaskTemplate,Task,AuditEvent
from .services import create_tasks,copy_contract

class WorkflowTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-934')
        self.customer=Customer.objects.create(name='Тестовый заказчик')
        self.operator=Operator.objects.create(name='Тестовый ТО')
        self.c=Contract.objects.create(customer=self.customer,operator=self.operator,start=date(2026,11,10),end=date(2026,11,20))
        ContractLine.objects.create(contract=self.c,description='Тур',amount=200000)
    def payment(self,kind,amount):
        Payment.objects.create(contract=self.c,kind=kind,amount=amount,method='Карта')
    def test_partial_payments_and_refunds(self):
        self.payment('customer',100000);self.payment('customer',100000)
        self.payment('operator',100000);self.payment('operator',80000)
        ContractLine.objects.create(contract=self.c,description='Уменьшение стоимости',amount=-50000)
        self.payment('customer_refund',50000);self.payment('operator_refund',45000)
        self.assertEqual((self.c.amount,self.c.paid,self.c.cost,self.c.profit,self.c.debt),(150000,150000,135000,15000,0))
    def test_task_generation_idempotent_and_manual_dates_preserved(self):
        TaskTemplate.objects.create(name='Проверить вылет',anchor='start',offset=-1)
        create_tasks(self.c);create_tasks(self.c)
        t=Task.objects.get();self.assertEqual(t.due,date(2026,11,9))
        t.due=date(2026,11,8);t.save();create_tasks(self.c)
        t.refresh_from_db();self.assertEqual(t.due,date(2026,11,8));self.assertEqual(Task.objects.count(),1)
    def test_copy_has_no_money_or_completion(self):
        self.payment('customer',200000)
        self.c.operator_paid=date(2026,10,21);self.c.save()
        c=copy_contract(self.c)
        self.assertEqual(c.amount,Decimal('200000'));self.assertEqual(c.paid,0)
        self.assertIsNone(c.operator_paid);self.assertEqual(c.number,'');self.assertFalse(c.task_set.exists())
    def test_authenticated_pages_and_mass_reschedule_audit(self):
        self.assertEqual(self.client.get('/').status_code,302)
        self.client.force_login(self.user)
        for url in ['/','/tasks/','/admin/crm/contract/add/']:
            self.assertEqual(self.client.get(url).status_code,200)
        t=Task.objects.create(title='Документы',due=date(2026,11,7),contract=self.c)
        r=self.client.post('/tasks/reschedule/',{'tasks':[t.pk],'due':'2026-11-08'})
        self.assertEqual(r.status_code,302);t.refresh_from_db();self.assertEqual(t.due,date(2026,11,8))
        self.assertEqual(AuditEvent.objects.get().changes['due']['old'],'2026-11-07')
    def test_unprivileged_user_cannot_view_finances(self):
        u=get_user_model().objects.create_user('limited',password='test-password-934')
        self.client.force_login(u)
        self.assertEqual(self.client.get('/').status_code,403)
        self.assertEqual(self.client.post('/tasks/reschedule/',{'due':'2026-11-08'}).status_code,403)
    def test_monthly_repeat_keeps_original_day(self):
        from .services import repeat_tasks
        t=Task.objects.create(title='Повтор',due=date(2027,1,31))
        copies=repeat_tasks(t,'month',3)
        self.assertEqual([x.due for x in copies],[date(2027,2,28),date(2027,3,31)])
    def test_admin_contract_creation_generates_selected_tasks(self):
        template=TaskTemplate.objects.create(name='Проверка',anchor='start',offset=-1)
        self.client.force_login(self.user)
        response=self.client.post('/admin/crm/contract/add/',{
            'date':'2026-10-21','customer':self.customer.pk,'operator':self.operator.pk,
            'start':'2026-11-10','end':'2026-11-20','task_templates':[template.pk],
            'lines-TOTAL_FORMS':'0','lines-INITIAL_FORMS':'0','lines-MIN_NUM_FORMS':'0','lines-MAX_NUM_FORMS':'1000',
            'bookings-TOTAL_FORMS':'0','bookings-INITIAL_FORMS':'0','bookings-MIN_NUM_FORMS':'0','bookings-MAX_NUM_FORMS':'1000','_save':'Сохранить'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Task.objects.get().due,date(2026,11,9))
