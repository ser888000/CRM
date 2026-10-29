from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission


class BookingPrefillTests(TestCase):
    url='/booking-prefill/demo/'
    origin='https://aborigen-tour.ru'

    def test_visitor_and_logged_user_without_permission_receive_no_payload(self):
        response=self.client.get(self.url,HTTP_ORIGIN=self.origin)
        self.assertEqual(response.status_code,403)
        self.assertNotIn('customer',response.json())
        user=get_user_model().objects.create_user('not-staff')
        self.client.force_login(user)
        response=self.client.get(self.url,HTTP_ORIGIN=self.origin)
        self.assertEqual(response.status_code,403)
        self.assertNotIn('tourists',response.json())

    def test_authorized_employee_gets_only_synthetic_data_from_allowed_origin(self):
        user=get_user_model().objects.create_user('prefill-employee')
        user.user_permissions.add(Permission.objects.get(content_type__app_label='crm',codename='view_contract'))
        self.client.force_login(user)
        response=self.client.get(self.url,HTTP_ORIGIN=self.origin)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['test_only'])
        self.assertEqual(response.json()['customer']['Email'],'test@example.invalid')
        self.assertEqual(len(response.json()['tourists']),2)
        self.assertEqual(response['Access-Control-Allow-Origin'],self.origin)
        self.assertEqual(response['Access-Control-Allow-Credentials'],'true')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn('Origin',response['Vary'])

    def test_foreign_origin_missing_origin_and_post_denied(self):
        user=get_user_model().objects.create_superuser('prefill-admin','','test')
        self.client.force_login(user)
        for origin in ('https://evil.invalid','https://aborigen-tour.ru.evil.invalid','http://aborigen-tour.ru','null',''):
            response=self.client.get(self.url,HTTP_ORIGIN=origin)
            self.assertEqual(response.status_code,403)
            self.assertNotIn('customer',response.json())
            self.assertNotIn('Access-Control-Allow-Origin',response)
        self.assertEqual(self.client.post(self.url,HTTP_ORIGIN=self.origin).status_code,405)

from datetime import date,timedelta
from django.utils import timezone
from .models import Contract,Customer,Operator,Tourist,ContractLine
from .booking_prefill import SELECTION,age_on

class RealBookingPrefillTests(TestCase):
    origin='https://aborigen-tour.ru'
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('real-prefill','','test');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Customer Only',main_phone='+79990000000',passport_number='TEST')
        self.contract=Contract.objects.create(customer=self.customer,operator=Operator.objects.create(name='TO'),number='TEST',start=date(2026,12,24))
        for index,birthday in enumerate((date(1980,1,1),date(1990,1,1),date(2016,12,25),date(2025,1,1))):
            person=Tourist.objects.create(surname='EXAMPLE'+chr(65+index),given_name='TEST',gender='female' if index%2 else 'male',birthday=birthday,passport_type='0',nationality='Россия')
            ContractLine.objects.create(contract=self.contract,tourist=person)
        person=self.contract.lines.first().tourist
        ContractLine.objects.create(contract=self.contract,tourist=person) # Additional price line must not duplicate the traveler.

    def choose(self):
        return self.client.post('/booking-prefill/select/',{'contract':self.contract.pk})

    def test_real_export_age_sort_dedup_and_customer_separate(self):
        self.assertEqual(self.choose().status_code,302)
        response=self.client.get('/booking-prefill/data/',HTTP_ORIGIN=self.origin)
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertFalse(data['test_only'])
        self.assertEqual([p['age'] for p in data['tourists']],[46,36,9,1])
        self.assertEqual(len(data['tourists']),4)
        self.assertEqual(data['customer']['Name'],'Customer Only')
        self.assertNotIn('Customer Only',[p['NAME'] for p in data['tourists']])
        self.assertEqual(Contract.objects.count(),1)
        self.assertIn('no-store',response['Cache-Control'])

    def test_selection_requires_csrf_and_export_requires_all_read_permissions(self):
        from django.test import Client
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post('/booking-prefill/select/',{'contract':self.contract.pk}).status_code,403)
        viewer=get_user_model().objects.create_user('contract-only')
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='crm',codename='view_contract'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get('/booking-prefill/data/',HTTP_ORIGIN=self.origin).status_code,403)
        self.assertEqual(self.client.post('/booking-prefill/select/',{'contract':self.contract.pk}).status_code,403)

    def test_expired_selection_and_foreign_origin_return_no_personal_data(self):
        self.choose();session=self.client.session;session[SELECTION]['expires']=timezone.now().timestamp()-1;session.save()
        response=self.client.get('/booking-prefill/data/',HTTP_ORIGIN=self.origin)
        self.assertEqual(response.status_code,409);self.assertNotIn('customer',response.json())
        self.choose();response=self.client.get('/booking-prefill/data/',HTTP_ORIGIN='https://evil.invalid')
        self.assertEqual(response.status_code,403);self.assertNotIn('customer',response.json())

    def test_missing_birthday_blocks_export_and_age_changes_on_birthday(self):
        self.assertEqual(age_on(date(2008,12,25),date(2026,12,24)),17)
        self.assertEqual(age_on(date(2008,12,24),date(2026,12,24)),18)
        self.choose();person=self.contract.lines.first().tourist;person.birthday=None;person.save()
        response=self.client.get('/booking-prefill/data/',HTTP_ORIGIN=self.origin)
        self.assertEqual(response.status_code,422)
        self.assertNotIn('tourists',response.json())
