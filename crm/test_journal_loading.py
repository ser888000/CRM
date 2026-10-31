from django.contrib.auth import get_user_model
from django.test import TestCase
from .models import Customer, Operator, Contract
from .card_forms import CardContractForm
from .customer_workspace import matching_rows


class JournalLoadingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('loading', 'loading@example.test', 'test-password')
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name='Selected customer')
        self.contract = Contract.objects.create(customer=self.customer, operator=Operator.objects.create(name='Operator'))
        Customer.objects.bulk_create([Customer(name=f'Unselected customer {n}') for n in range(100)])

    def test_contract_renders_only_selected_customer_but_accepts_other_selection(self):
        response = self.client.get(f'/contracts/{self.contract.pk}/')
        self.assertContains(response, 'data-remote-choices="/contracts/choices/customers/"')
        self.assertNotContains(response, 'Unselected customer 99')
        other = Customer.objects.get(name='Unselected customer 99')
        form = CardContractForm({'customer': other.pk}, instance=self.contract)
        self.assertEqual(form.fields['customer'].clean(other.pk), other)
        self.assertEqual(len(list(form.fields['customer'].widget.choices)), 2)
        choices = self.client.get('/contracts/choices/customers/', {'q': 'Unselected customer'}).json()['choices']
        self.assertEqual(len(choices), 30)
        self.client.logout()
        self.assertEqual(self.client.get('/contracts/choices/customers/', {'q': 'Selected'}).status_code, 302)

    def test_directory_counts_do_not_add_queries_per_customer(self):
        with self.assertNumQueries(2):
            rows = matching_rows({'kind': '', 'name': '', 'phone': '', 'email': ''})
        self.assertEqual(len(rows), 101)
        self.assertEqual(sum(row['values']['contracts'] for row in rows), 1)
        response = self.client.get('/customers/')
        self.assertEqual(response.context['count'], 101)
        self.assertContains(response, 'Unselected customer 99')
