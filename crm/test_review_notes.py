from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Customer,Operator,Contract,PaymentMethod,Payment,PaymentOperation
from .card_forms import CardPaymentForm
from .tourvisor import normalize_order
from .test_tourvisor import sample

class ReviewNotesTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Тестовый заказчик');self.operator=Operator.objects.create(name='Тестовый ТО')
        self.c=Contract.objects.create(customer=self.customer,operator=self.operator,number='TEST-101',country='Египет')
    def test_journal_restores_filters_sort_and_clears_explicitly(self):
        self.client.get('/',{'f_country':['Египет','Турция'],'sort':'-date','customer':'Тестовый'})
        self.client.get(f'/contracts/{self.c.pk}/');self.client.get('/tasks/')
        response=self.client.get('/',follow=True)
        self.assertEqual(response.context['sort'],'-date');self.assertEqual(response.wsgi_request.GET.getlist('f_country'),['Египет','Турция'])
        self.assertEqual(response.context['count'],1)
        response=self.client.get('/?reset=1',follow=True)
        self.assertFalse(response.wsgi_request.GET);self.assertFalse(self.client.session.get('contract_journal'))
    def test_journal_state_does_not_cross_users(self):
        self.client.get('/',{'customer':'Missing'})
        self.client.logout();user=get_user_model().objects.create_superuser('other','other@example.test','test-password-456');self.client.force_login(user)
        self.assertEqual(self.client.get('/').context['count'],1)
    def test_removed_link_not_kept_or_validated(self):
        raw=sample();raw['operatorlink']='not a valid URL'
        self.assertNotIn('operator_link',normalize_order(raw)['contract'])
        response=self.client.get(f'/contracts/{self.c.pk}/')
        self.assertNotContains(response,'name="operator_link"');self.assertNotContains(response,'Договор № TEST-101')
        self.assertContains(response,'<h1>TEST-101</h1>',html=True)
    def test_operation_dictionary_labels_defaults_and_balances(self):
        operation=PaymentOperation.objects.get(code='customer');operation.name='Оплата заказчиком';operation.is_default=True;operation.save()
        form=CardPaymentForm();self.assertEqual(form['kind'].value(),'customer');self.assertEqual(dict(form.fields['kind'].choices)['customer'],'Оплата заказчиком')
        method=PaymentMethod.objects.create(name='Карта')
        payment=Payment.objects.create(contract=self.c,kind='customer',amount=100,method=method)
        Payment.objects.create(contract=self.c,kind='customer_refund',amount=25,method=method)
        customer_admin=self.client.get('/admin/crm/customer/add/')
        self.assertEqual(customer_admin.context['adminform'].form['kind'].value(),'person')
        self.assertEqual(payment.get_kind_display(),'Оплата заказчиком');self.assertEqual(self.c.paid,75)
        response=self.client.get('/admin/crm/paymentoperation/')
        self.assertContains(response,'Оплата заказчиком');self.assertFalse(response.context['has_add_permission'])
