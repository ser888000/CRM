from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Contract,Customer,Operator,ContractLine,Payment,PaymentMethod,Tourist
from .card_forms import CustomerCardForm,TouristCardForm

class ContractFinishingTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
        self.c=Contract.objects.create(customer=Customer.objects.create(name='Заказчик'),operator=Operator.objects.create(name='ТО'))
        self.method=PaymentMethod.objects.create(name='Карта')
    def test_commission_uses_contract_and_net_operator_cost(self):
        ContractLine.objects.create(contract=self.c,description='Тур',amount=100000)
        Payment.objects.create(contract=self.c,kind='operator',amount=90000,method=self.method)
        Payment.objects.create(contract=self.c,kind='operator_refund',amount=5000,method=self.method)
        self.assertEqual(self.c.commission_percent,Decimal('15'))
        response=self.client.get(f'/contracts/{self.c.pk}/')
        self.assertContains(response,'Комиссия');self.assertContains(response,'15,00')
        Payment.objects.create(contract=self.c,kind='operator',amount=20000,method=self.method)
        self.assertEqual(self.c.commission_percent,Decimal('-5'))
    def test_zero_contract_amount_is_not_divided(self):
        self.assertIsNone(self.c.commission_percent)
        response=self.client.get(f'/contracts/{self.c.pk}/');self.assertEqual(response.status_code,200)
        self.assertContains(response,'Комиссия')
    def test_customer_address_and_notes_are_last(self):
        fields=list(CustomerCardForm().fields)
        self.assertEqual(fields[-2:],['address','passport'])
        self.assertEqual(CustomerCardForm().fields['passport'].label,'Примечание')
        customer=self.c.customer;customer.passport='Старое значение';customer.save()
        self.assertEqual(CustomerCardForm(instance=customer)['passport'].value(),'Старое значение')
    def test_tourist_full_name_order_and_server_composition(self):
        form=TouristCardForm({'surname':'  EXAMPLE  ','given_name':'  TEST  ','name':'Ошибочное ФИО'})
        self.assertTrue(form.is_valid(),form.errors);tourist=form.save()
        self.assertEqual(tourist.name,'EXAMPLE TEST');self.assertEqual(list(form.fields)[:3],['surname','given_name','name'])
        tourist.given_name='NEW';tourist.save(update_fields=['given_name']);tourist.refresh_from_db()
        self.assertEqual(tourist.name,'EXAMPLE NEW')
        self.assertContains(self.client.get('/admin/crm/tourist/add/'),'crm/customer_name_v2.js')
    def test_card_add_tourist_without_posting_computed_name(self):
        response=self.client.post(f'/contracts/{self.c.pk}/',{'action':'tourist','tourist-new-surname':'EXAMPLE','tourist-new-given_name':'TEST'})
        self.assertEqual(response.status_code,302);self.assertEqual(self.c.lines.get().tourist.name,'EXAMPLE TEST')
