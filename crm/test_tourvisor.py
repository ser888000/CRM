import copy
import json
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch,MagicMock
from django.test import TestCase,SimpleTestCase,override_settings
from django.contrib.auth import get_user_model
from .models import Contract,Customer,Operator,ContractLine,Payment,PaymentMethod,Task,TaskTemplate
from .tourvisor import normalize_order,apply_order,fetch_order,TourvisorError,GROUPS
from .services import copy_contract


def sample():
    o=json.loads((Path(__file__).parent.parent/'docs/examples/tourvisor-online-anonymized.json').read_text())['orders']['order'][0]
    o['id']='2299358'
    # Distinct synthetic tourists, independent of the real person's data.
    for i,t in enumerate(o['tourist']):
        t['surname']='EXAMPLE'+str(i);t['passportseries']='00';t['passportnumber']='00000'+str(i)
    return o

class ImportTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123')
        self.client.force_login(self.user)
        self.order=sample()
    def test_atomic_import_repeat_and_copy(self):
        template=TaskTemplate.objects.create(name='Вылет',anchor='start',offset=-1,copy_flights=True)
        c=apply_order(self.order,self.user,set(GROUPS),[template])
        self.assertEqual(c.number,'2299358');self.assertEqual(c.amount,Decimal('200000'))
        self.assertEqual(c.lines.filter(tourist__isnull=False).count(),2)
        self.assertIn('XX1234',Task.objects.get().description)
        with self.assertRaises(TourvisorError):apply_order(self.order,self.user,set(GROUPS))
        self.assertEqual(Contract.objects.count(),1)
        cloned=copy_contract(c);self.assertIsNone(cloned.tourvisor_id)
        self.assertEqual(cloned.amount,c.amount)
    def test_update_preserves_payments_local_notes_flights_and_tasks(self):
        c=apply_order(self.order,self.user,set(GROUPS))
        method=PaymentMethod.objects.create(name='Карта')
        Payment.objects.create(contract=c,kind='customer',amount=50000,method=method)
        Payment.objects.create(contract=c,kind='operator',amount=100000,method=method)
        c.notes='Местное примечание';c.flights='Местный рейс';c.customer.phones='Дополнительный телефон';c.customer.save();c.save()
        original_lines=c.lines.count()
        changed=copy.deepcopy(self.order);changed['price']='210000';changed['transport'][0]['number']='XX9999'
        c=apply_order(changed,self.user,{'amount','transport','customer'},expected=c.pk,expected_version=str(c.updated_at))
        self.assertEqual(c.amount,Decimal('210000'));self.assertEqual(c.paid,50000);self.assertEqual(c.cost,100000)
        self.assertEqual(c.notes,'Местное примечание');self.assertEqual(c.flights,'Местный рейс')
        self.assertEqual(c.customer.phones,'Дополнительный телефон')
        self.assertEqual(c.lines.count(),original_lines+1)
        apply_order(changed,self.user,{'amount'},expected=c.pk)
        self.assertEqual(c.lines.count(),original_lines+1)
    def test_bad_currency_and_bad_data_never_create_contract(self):
        self.order['currency']='USD'
        with self.assertRaises(TourvisorError):apply_order(self.order,self.user,set(GROUPS))
        self.assertFalse(Contract.objects.exists());self.assertFalse(Customer.objects.exists())
        self.order['currency']='RUB';self.order['price']='NaN'
        with self.assertRaises(TourvisorError):normalize_order(self.order)
    def test_preview_does_not_save_then_confirm_is_idempotent(self):
        with patch('crm.import_views.fetch_order',return_value=self.order):
            response=self.client.post('/tourvisor/import/',{'action':'lookup','order_id':'2299358'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Новый договор')
        self.assertFalse(Contract.objects.exists())
        token=self.client.session['tourvisor_preview']['token']
        payload={'action':'confirm','token':token,'groups':list(GROUPS),'end':'2026-12-08'}
        response=self.client.post('/tourvisor/import/',payload)
        self.assertEqual(response.status_code,302)
        response=self.client.post('/tourvisor/import/',payload)
        self.assertEqual(response.status_code,200)
        self.assertEqual(Contract.objects.count(),1)
    def test_error_and_access_control(self):
        with patch('crm.import_views.fetch_order',side_effect=TourvisorError('Турвизор временно недоступен')):
            response=self.client.post('/tourvisor/import/',{'action':'lookup','order_id':'2299358'})
        self.assertContains(response,'временно недоступен');self.assertFalse(Contract.objects.exists())
        user=get_user_model().objects.create_user('limited',password='test-password-123')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/tourvisor/import/').status_code,403)
    def test_stale_preview_and_manual_duplicate_rejected(self):
        c=apply_order(self.order,self.user,set(GROUPS));old=str(c.updated_at)
        c.notes='changed';c.save()
        with self.assertRaises(TourvisorError):apply_order(self.order,self.user,{'amount'},expected=c.pk,expected_version=old)
        c.tourvisor_id=None;c.save()
        with self.assertRaises(TourvisorError):apply_order(self.order,self.user,set(GROUPS))
    def test_imported_identifiers_readonly_and_supplements_render(self):
        c=apply_order(self.order,self.user,set(GROUPS))
        response=self.client.get(f'/admin/crm/contract/{c.pk}/change/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'name="number"')
        self.assertNotContains(response,'name="date"')
        self.assertContains(response,'XX1234')

class ClientErrors(TestCase):
    def test_database_error_and_auth_error_are_sanitized(self):
        for body in [b'Error connecting database! Please, try again later.',b'{"error":{"errormessage":"Authorisation Error."}}',b'{"orders":{"order":[]}}']:
            mock=MagicMock();mock.open.return_value.__enter__.return_value.read.return_value=body
            with patch.dict('os.environ',{'TOURVISOR_API_KEY':'SENSITIVE-TEST-KEY'}),patch('crm.tourvisor.request.build_opener',return_value=mock):
                with self.assertRaises(TourvisorError) as caught:fetch_order('2299358')
                self.assertNotIn('SENSITIVE-TEST-KEY',str(caught.exception));self.assertNotIn('authkey',str(caught.exception))

    def test_missing_key_and_http_failure_do_not_expose_details(self):
        from urllib.error import HTTPError
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(TourvisorError):fetch_order('2299358')
        mock=MagicMock();mock.open.side_effect=HTTPError('https://example.test/?authkey=SENSITIVE',503,'unavailable',None,None)
        with patch.dict('os.environ',{'TOURVISOR_API_KEY':'SENSITIVE'}),patch('crm.tourvisor.request.build_opener',return_value=mock):
            with self.assertRaises(TourvisorError) as caught:fetch_order('2299358')
            self.assertNotIn('SENSITIVE',str(caught.exception))

class OptionalGroups(TestCase):
    def test_new_import_respects_optional_sections(self):
        user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123')
        c=apply_order(sample(),user,{'customer','tour','amount'})
        self.assertEqual(c.amount,200000)
        self.assertEqual(c.hotel,'')
        self.assertFalse(c.lines.filter(tourist__isnull=False).exists())
        self.assertNotIn('transport',c.source_data)
