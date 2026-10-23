from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Customer,Operator,Contract,ContractLine,Payment,PaymentMethod,Task
from .templatetags.money import money

class JournalTests(TestCase):
    def setUp(self):
        user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123')
        self.client.force_login(user)
        self.c=Contract.objects.create(customer=Customer.objects.create(name='Клиент'),operator=Operator.objects.create(name='ТО'),number='100')
        ContractLine.objects.create(contract=self.c,description='Тур',amount=1234567.89)
        m=PaymentMethod.objects.create(name='Карта')
        for kind,amount in [('customer',1000),('customer_refund',100),('operator',800),('operator_refund',50)]:
            Payment.objects.create(contract=self.c,kind=kind,amount=amount,method=m)
    def test_money_format(self):
        self.assertEqual(money('1234567.89'),'1 234 567,89');self.assertEqual(money('-0.01'),'-0,01')
    def test_finance_totals_and_filters(self):
        response=self.client.get('/finances/')
        self.assertEqual(response.context['count'],4)
        self.assertEqual(response.context['incoming'],1050);self.assertEqual(response.context['outgoing'],900)
        response=self.client.get('/finances/?kind=customer_refund')
        self.assertEqual(response.context['count'],1);self.assertEqual(response.context['outgoing'],100)
        response=self.client.get('/admin/crm/payment/?kind__exact=operator')
        self.assertEqual(response.context['financial_totals']['count'],1)
        self.assertEqual(response.context['financial_totals']['outgoing'],'800,00')
    def test_contract_totals_and_all_tasks(self):
        response=self.client.get('/')
        self.assertContains(response,'1 234 567,89');self.assertEqual(response.context['count'],1)
        self.assertEqual(self.client.get('/?number=missing').context['count'],0)
        self.assertEqual(self.client.get('/admin/crm/contract/').context['contract_totals']['count'],1)
        Task.objects.create(title='Запланировано',due=date.today())
        Task.objects.create(title='Выполнено',due=date.today(),done=True)
        self.assertEqual(len(self.client.get('/tasks/?period=all').context['rows']),2)
        self.assertEqual(len(self.client.get('/tasks/?period=planned').context['rows']),1)

    def test_localized_money_input_and_navigation(self):
        from .forms import PaymentForm
        form=PaymentForm(data={'contract':self.c.pk,'kind':'customer','date':'2026-10-23','amount':'1 234,56','method':PaymentMethod.objects.get().pk})
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(str(form.cleaned_data['amount']),'1234.56')
        self.assertContains(self.client.get('/admin/crm/contract/add/'),'Договоры: таблица')
        from .widgets import MoneyInput
        self.assertIn('0,00',MoneyInput().render('amount',0))
