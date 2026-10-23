from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Customer,Operator,Contract,ContractLine,Payment,TaskTemplate,Task,AuditEvent,PaymentMethod,Booking
from .services import create_tasks,copy_contract

class WorkflowTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-934')
        self.customer=Customer.objects.create(name='Тестовый заказчик')
        self.operator=Operator.objects.create(name='Тестовый ТО')
        self.method=PaymentMethod.objects.create(name='Карта')
        self.c=Contract.objects.create(customer=self.customer,operator=self.operator,start=date(2026,11,10),end=date(2026,11,20))
        ContractLine.objects.create(contract=self.c,description='Тур',amount=200000)
    def payment(self,kind,amount):
        Payment.objects.create(contract=self.c,kind=kind,amount=amount,method=self.method)
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
            'adults':'0','children':'0','infants':'0','source_currency':'RUB','date':'2026-10-21','customer':self.customer.pk,'operator':self.operator.pk,
            'start':'2026-11-10','end':'2026-11-20','task_templates':[template.pk],f'task_due_{template.pk}':'2026-11-09',
            'lines-TOTAL_FORMS':'0','lines-INITIAL_FORMS':'0','lines-MIN_NUM_FORMS':'0','lines-MAX_NUM_FORMS':'1000',
            'payments-TOTAL_FORMS':'0','payments-INITIAL_FORMS':'0','payments-MIN_NUM_FORMS':'0','payments-MAX_NUM_FORMS':'1000',
            'bookings-TOTAL_FORMS':'0','bookings-INITIAL_FORMS':'0','bookings-MIN_NUM_FORMS':'0','bookings-MAX_NUM_FORMS':'1000','_save':'Сохранить'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Task.objects.get().due,date(2026,11,9))

    def test_existing_contract_and_task_edit_pages(self):
        TaskTemplate.objects.create(name='Дополнительная задача',anchor='start')
        self.client.force_login(self.user)
        response=self.client.get(f'/admin/crm/contract/{self.c.pk}/change/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'name="task_templates"')
        task=Task.objects.create(title='Проверить вылет',due=date(2026,11,9))
        response=self.client.get(f'/admin/crm/task/{task.pk}/change/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'name="repeat"')
        self.assertNotContains(response,'name="occurrences"')
        response=self.client.post(f'/admin/crm/task/{task.pk}/change/',{
            'title':task.title,'due':'2026-11-08','done':'on','_save':'Сохранить'})
        self.assertEqual(response.status_code,302)
        task.refresh_from_db()
        self.assertTrue(task.done)
        self.assertEqual(task.due,date(2026,11,8))
        self.assertEqual(Task.objects.count(),1)

    def test_booking_links_encode_numbers_and_reject_bad_templates(self):
        from django.core.exceptions import ValidationError
        self.operator.booking_url_template='https://example.test/book/{booking}'
        self.operator.full_clean();self.operator.save()
        b=Booking.objects.create(contract=self.c,number='AB/12 ?')
        self.assertEqual(b.booking_link,'https://example.test/book/AB%2F12%20%3F')
        for bad in ['javascript:alert({booking})','https://example.test/{unknown}','https://example.test/']:
            self.operator.booking_url_template=bad
            with self.assertRaises(ValidationError):self.operator.full_clean()

    def test_custom_task_dates_and_flights(self):
        template=TaskTemplate.objects.create(name='Вылет',anchor='start',offset=-1,copy_flights=True)
        self.c.flights='SU 123 туда; SU 124 обратно';self.c.save()
        create_tasks(self.c,[template],{template.pk:date(2026,11,7)})
        t=Task.objects.get()
        self.assertEqual(t.description,self.c.flights)
        self.assertEqual(t.due,date(2026,11,7))
        create_tasks(self.c,[template],{template.pk:date(2026,11,8)})
        self.assertEqual(Task.objects.count(),1)
        t.refresh_from_db();self.assertEqual(t.due,date(2026,11,7))

    def test_last_minute_default_task_dates(self):
        from .services import task_due
        self.c.date=date(2026,11,9)
        template=TaskTemplate.objects.create(name='Документы',anchor='start',offset=-3)
        self.assertEqual(task_due(self.c,template),self.c.date)

    def test_payment_customer_filter_and_validation(self):
        from .forms import PaymentForm
        other=Customer.objects.create(name='Другой заказчик')
        form=PaymentForm(data={'customer':other.pk,'contract':self.c.pk,'date':'2026-11-01','kind':'customer','amount':'500.00','method':self.method.pk})
        self.assertFalse(form.is_valid());self.assertIn('contract',form.errors)
        form=PaymentForm(data={'contract':self.c.pk,'date':'2026-11-01','kind':'customer','amount':'500.00','method':self.method.pk,'rate':'90.12'})
        self.assertTrue(form.is_valid(),form.errors)
        self.client.force_login(self.user)
        r=self.client.get('/admin/crm/payment/contracts-for-customer/',{'customer':self.customer.pk})
        self.assertEqual([c['id'] for c in r.json()['contracts']],[self.c.pk])
        r=self.client.get('/admin/crm/payment/contracts-for-customer/',{'customer':other.pk})
        self.assertEqual(r.json()['contracts'],[])
        self.payment('customer',500)
        response=self.client.get('/admin/crm/payment/')
        self.assertContains(response,self.customer.name)

    def test_contract_edit_can_add_payment_inline(self):
        self.client.force_login(self.user)
        response=self.client.post(f'/admin/crm/contract/{self.c.pk}/change/',{
            'adults':'0','children':'0','infants':'0','source_currency':'RUB','date':'2026-10-22','customer':self.customer.pk,'operator':self.operator.pk,'start':'2026-11-10','end':'2026-11-20',
            'lines-TOTAL_FORMS':'0','lines-INITIAL_FORMS':'0','lines-MIN_NUM_FORMS':'0','lines-MAX_NUM_FORMS':'1000',
            'bookings-TOTAL_FORMS':'0','bookings-INITIAL_FORMS':'0','bookings-MIN_NUM_FORMS':'0','bookings-MAX_NUM_FORMS':'1000',
            'payments-TOTAL_FORMS':'1','payments-INITIAL_FORMS':'0','payments-MIN_NUM_FORMS':'0','payments-MAX_NUM_FORMS':'1000',
            'payments-0-date':'2026-10-22','payments-0-kind':'customer','payments-0-amount':'1250.00','payments-0-method':self.method.pk,'_save':'Сохранить'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.c.paid,Decimal('1250'))
        payment=Payment.objects.get()
        self.assertEqual(payment.contract_id,self.c.pk)
        self.assertTrue(AuditEvent.objects.filter(object_type='crm.Payment',object_id=str(payment.pk)).exists())

    def test_task_creation_controls_and_existing_payment_edit_render(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/admin/crm/task/add/'),'name="occurrences"')
        self.payment('customer',500)
        response=self.client.get(f'/admin/crm/payment/{Payment.objects.get().pk}/change/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'name="rate"')
        self.assertEqual(Payment._meta.get_field('rate').decimal_places,2)

    def test_task_list_shows_operator_booking_and_link(self):
        self.operator.booking_url_template='https://example.test/{booking}';self.operator.save()
        Booking.objects.create(contract=self.c,number='BOOK-123')
        Task.objects.create(title='Вылет',due=date(2026,11,9),contract=self.c)
        self.client.force_login(self.user)
        r=self.client.get('/tasks/?period=all')
        self.assertContains(r,'BOOK-123')
        self.assertContains(r,'https://example.test/BOOK-123')
        self.assertContains(r,self.operator.name)

    def test_selected_task_requires_explicit_date(self):
        from .admin import ContractAdmin
        from django.contrib.admin.sites import site
        from django.test import RequestFactory
        template=TaskTemplate.objects.create(name='Проверка',anchor='start',offset=-1)
        request=RequestFactory().get('/admin/crm/contract/add/');request.user=self.user
        form_class=ContractAdmin(Contract,site).get_form(request)
        form=form_class(data={'adults':'0','children':'0','infants':'0','source_currency':'RUB','date':'2026-10-22','customer':self.customer.pk,'operator':self.operator.pk,'task_templates':[template.pk]})
        self.assertFalse(form.is_valid())
        self.assertIn(f'task_due_{template.pk}',form.errors)

    def test_contract_forms_offer_exit_without_saving(self):
        self.client.force_login(self.user)
        before=Contract.objects.count()
        for url in ['/admin/crm/contract/add/',f'/admin/crm/contract/{self.c.pk}/change/']:
            response=self.client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'Выйти без сохранения')
            self.assertContains(response,'href="/" onclick="return confirm(')
        self.client.get('/')
        self.assertEqual(Contract.objects.count(),before)
