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
