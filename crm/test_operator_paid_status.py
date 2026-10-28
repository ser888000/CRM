from datetime import date
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase,Client
from .models import Contract,Customer,Operator,Payment,AuditEvent,Booking


class OperatorPaidTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('operator-status','','test')
        self.client.force_login(self.user)
        self.contract=Contract.objects.create(customer=Customer.objects.create(name='Test'),operator=Operator.objects.create(name='TO'),number='PAID',date=date(2026,10,28))
        self.url=f'/contracts/{self.contract.pk}/operator-paid/'

    def test_status_updates_only_flag_with_audit_and_conflict_protection(self):
        version=str(self.contract.updated_at)
        response=self.client.post(self.url,{'paid':'1','version':version})
        self.assertEqual(response.status_code,200)
        self.contract.refresh_from_db();self.assertTrue(self.contract.operator_paid_in_full)
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(AuditEvent.objects.get(action='operator_payment_status').changes,
                         {'operator_paid_in_full':{'old':False,'new':True}})
        self.assertEqual(self.client.post(self.url,{'paid':'0','version':version}).status_code,409)
        self.contract.refresh_from_db();self.assertTrue(self.contract.operator_paid_in_full)
        self.assertEqual(self.client.post(self.url,{'paid':'0','version':str(self.contract.updated_at)}).status_code,200)
        self.contract.refresh_from_db();self.assertFalse(self.contract.operator_paid_in_full)

    def test_permissions_post_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code,405)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url,{'paid':'1','version':str(self.contract.updated_at)}).status_code,403)
        user=get_user_model().objects.create_user('read-only')
        user.user_permissions.add(Permission.objects.get(content_type__app_label='crm',codename='view_contract'))
        self.client.force_login(user)
        self.assertEqual(self.client.post(self.url,{'paid':'1','version':str(self.contract.updated_at)}).status_code,403)

    def test_journal_button_version_and_shared_booking_deadline(self):
        journal=self.client.get('/',{'start':'2026-10-01','end':'2026-10-31'})
        self.assertContains(journal,'data-version="'+str(self.contract.updated_at)+'"')
        self.assertContains(journal,'Оплачено ТО')
        self.assertNotContains(journal,'Дата оплаты ТО')
        Booking.objects.create(contract=self.contract,number='ONE')
        Booking.objects.create(contract=self.contract,number='TWO')
        response=self.client.post(f'/contracts/{self.contract.pk}/?tab=bookings',
            {'action':'operator_due','version':str(self.contract.updated_at),'due':'2026-11-01'})
        self.assertEqual(response.status_code,302)
        self.contract.refresh_from_db();self.assertEqual(self.contract.operator_due,date(2026,11,1))
        page=self.client.get(f'/contracts/{self.contract.pk}/?tab=bookings')
        self.assertContains(page,'Срок оплаты ТО (общий для всех броней)')
        self.assertEqual(Booking.objects.filter(contract=self.contract).count(),2)
        self.assertNotIn('operator_due',page.context['form'].fields)
        self.assertNotIn('operator_paid_in_full',page.context['form'].fields)
