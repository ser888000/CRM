from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from .models import Customer,Operator,Contract,ContractLine,Payment,PaymentMethod,Task
from .finance_views import FinanceEditor
from .task_views import TaskEditorForm

class CustomerLinksTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('links','','password');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Проверочный Иван',birthday=date(1980,1,2),main_phone='+79990000000')
        self.other=Customer.objects.create(name='Другой заказчик')
        self.operator=Operator.objects.create(name='ТО')
        self.contract=Contract.objects.create(customer=self.customer,operator=self.operator,number='123',date=date(2020,2,1),legacy_amount_adjustment=5)
        self.other_contract=Contract.objects.create(customer=self.other,operator=self.operator,number='OTHER')
        ContractLine.objects.create(contract=self.contract,amount=100)
        ContractLine.objects.create(contract=self.contract,amount=200)
        self.method=PaymentMethod.objects.create(name='Касса')
    def test_customer_tasks_payments_and_legacy_payer_are_linked(self):
        shared=Task.objects.create(title='Общая',customer=self.customer,due=date.today())
        linked=Task.objects.create(title='Договорная',contract=self.contract,due=date.today())
        Task.objects.create(title='Чужая',customer=self.other,due=date.today())
        payments=[Payment.objects.create(contract=self.contract,kind='customer',amount=100,method=self.method),Payment.objects.create(contract=self.contract,kind='operator',amount=40,method=self.method),Payment.objects.create(contract=self.other_contract,legacy_payer=self.customer,kind='customer',amount=30,method=self.method)]
        Payment.objects.create(contract=self.other_contract,kind='customer',amount=999,method=self.method)
        response=self.client.get(f'/customers/{self.customer.pk}/')
        self.assertEqual({t.pk for t in response.context['customer_tasks']},{shared.pk,linked.pk})
        self.assertEqual({p.pk for p in response.context['customer_payments']},{p.pk for p in payments})
        self.assertEqual(response.context['customer_payment_totals'],{'incoming':Decimal('130'),'outgoing':Decimal('40')})
        self.assertContains(response,'<td class="numeric">100,00</td>',html=True)
        self.assertContains(response,'Задачи заказчика');self.assertContains(response,'Финансы заказчика');self.assertNotContains(response,'Чужая')
        user=get_user_model().objects.create_user('only-customer');user.user_permissions.add(Permission.objects.get(codename='view_customer'));self.client.force_login(user)
        response=self.client.get(f'/customers/{self.customer.pk}/')
        self.assertNotContains(response,'Задачи заказчика');self.assertNotContains(response,'Финансы заказчика')
    def test_shared_search_labels_scoping_and_initial_choices(self):
        customer=self.client.get('/finances/customers/',{'q':'пРОвер'}).json()['choices'][0]
        self.assertIn('02.01.1980',customer['label']);self.assertIn('+79990000000',customer['label'])
        finance=self.client.get('/finances/contracts/',{'customer':self.customer.pk}).json()['contracts']
        tasks=self.client.get('/tasks/choices/contracts/',{'customer':self.customer.pk}).json()['choices']
        self.assertEqual(finance,tasks);self.assertEqual([c['id'] for c in finance],[self.contract.pk])
        self.assertIn('01.02.2020',finance[0]['label']);self.assertIn('305,00',finance[0]['label'])
        payment=Payment.objects.create(contract=self.contract,kind='customer',amount=10,method=self.method)
        form=FinanceEditor(instance=payment)
        self.assertIn('305,00',str(form.fields['contract'].widget.choices))
        self.assertEqual(len(form.fields['customer'].widget.choices),2)
        self.assertNotIn('crm/payment_customer_v2.js',form.media._js)
        self.assertEqual(form.fields['contract'].widget.attrs['data-customer-filter'],'id_customer')
        locked=Task.objects.create(title='Закреплённая',due=date.today(),customer=self.customer,contract=self.contract,origin_key='locked-choice')
        bound=TaskEditorForm({'title':locked.title,'due':'invalid'},instance=locked,user=self.user)
        self.assertEqual(len(bound.fields['contract'].widget.choices),2)
        self.assertEqual(len(bound.fields['customer'].widget.choices),2)
        task_form=self.client.get('/tasks/new/').context
        self.assertEqual([[f.name for f in group] for group in task_form['task_field_groups']],[['task_type','due','employee'],['description','result','done'],['customer','contract'],['operator','booking_number'],['repeat','occurrences']])
    def test_search_is_bounded_and_does_not_expose_amounts_to_task_only_user(self):
        Contract.objects.bulk_create([Contract(customer=self.customer,operator=self.operator,number=f'MANY-{n}') for n in range(50)])
        self.assertEqual(len(self.client.get('/finances/contracts/',{'customer':self.customer.pk}).json()['contracts']),30)
        user=get_user_model().objects.create_user('task-only');user.user_permissions.add(Permission.objects.get(codename='view_task'));self.client.force_login(user)
        values=self.client.get('/tasks/choices/contracts/',{'q':'123'}).json()['choices']
        self.assertNotIn('305,00',values[0]['label'])
        self.assertEqual(self.client.get('/finances/customers/',{'q':'провер'}).status_code,403)
    def test_related_sections_paginate_and_totals_cover_every_page(self):
        Task.objects.bulk_create([Task(title='Задача',customer=self.customer,due=date.today()) for _ in range(101)])
        Payment.objects.bulk_create([Payment(contract=self.contract,kind='customer',amount=1,method=self.method) for _ in range(101)])
        response=self.client.get(f'/customers/{self.customer.pk}/?task_page=2&finance_page=2')
        self.assertEqual(len(response.context['customer_tasks']),1);self.assertEqual(len(response.context['customer_payments']),1)
        self.assertEqual(response.context['customer_payment_totals']['incoming'],101)
        self.assertContains(response,'#customer-tasks');self.assertContains(response,'#customer-finances')
