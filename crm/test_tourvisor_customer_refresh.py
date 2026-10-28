import copy
from unittest.mock import patch
from django.utils import timezone
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Contract, Customer, TourvisorBatch, TourvisorBatchRow
from .test_tourvisor import sample
from .tourvisor import apply_order, normalize_order, TourvisorError, GROUPS
from .batch_views import summarize


class TourvisorCustomerRefreshTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('refresh-admin','','test')
        self.client.force_login(self.user)
        self.order=sample()

    def test_refresh_shared_card_preserves_identity_notes_and_contract_links(self):
        contract=apply_order(self.order,self.user,set(GROUPS))
        customer=contract.customer
        customer.passport='Local notes';customer.phones='Extra contact';customer.save()
        other=Contract.objects.create(customer=customer,operator=contract.operator,number='LEGACY')
        identity=customer.exchange_id
        changed=copy.deepcopy(self.order);changed['phone']='79991112233'
        apply_order(changed,self.user,{'customer'},expected=contract.pk,expected_version=str(contract.updated_at))
        customer.refresh_from_db();other.refresh_from_db();contract.refresh_from_db()
        self.assertEqual(customer.main_phone,'79991112233')
        self.assertEqual(customer.exchange_id,identity)
        self.assertEqual((customer.passport,customer.phones),('Local notes','Extra contact'))
        self.assertEqual((contract.customer_id,other.customer_id),(customer.pk,customer.pk))
        self.assertEqual(Customer.objects.count(),1)

    def test_first_import_updates_selected_customer_only_with_explicit_option(self):
        first=apply_order(self.order,self.user,set(GROUPS))
        changed=copy.deepcopy(self.order);changed['id']='2299359';changed['client_pass_number']='NEW-PASSPORT'
        second=apply_order(changed,self.user,set(GROUPS),customer_choice=str(first.customer_id))
        self.assertEqual(second.customer_id,first.customer_id)
        first.customer.refresh_from_db()
        self.assertNotEqual(first.customer.passport_number,'NEW-PASSPORT')
        changed['id']='2299360'
        third=apply_order(changed,self.user,set(GROUPS),customer_choice=str(first.customer_id),update_customer=True)
        first.customer.refresh_from_db()
        self.assertEqual(third.customer_id,first.customer_id)
        self.assertEqual(first.customer.passport_number,'NEW-PASSPORT')
        self.assertEqual(Customer.objects.count(),1)

    def test_review_selected_customer_shows_current_data_without_writing(self):
        first=apply_order(self.order,self.user,set(GROUPS))
        changed=copy.deepcopy(self.order);changed['id']='2299359';changed['phone']='79991112233'
        with patch('crm.import_views.fetch_order',return_value=changed):
            response=self.client.post('/tourvisor/import/',{'action':'lookup','order_id':changed['id']})
        form=response.context['confirm']
        response=self.client.post('/tourvisor/import/',{
            'action':'review_customer','token':form['token'].value(),'groups':list(GROUPS),
            'customer_choice':str(first.customer_id),'end':'2026-12-20'})
        self.assertEqual(Contract.objects.count(),1)
        customer_section=response.context['sections'][0]
        phone=next(c for c in customer_section['changes'] if c['label']=='Основной телефон')
        self.assertEqual(phone['old'],first.customer.main_phone)
        self.assertEqual(phone['new'],'79991112233')
        self.assertContains(response,'name="update_customer"')

    def test_boundary_blocks_old_new_contract_without_any_writes(self):
        old=copy.deepcopy(self.order);old['id']='2299357'
        with self.assertRaises(TourvisorError):apply_order(old,self.user,set(GROUPS))
        self.assertFalse(Contract.objects.exists());self.assertFalse(Customer.objects.exists())
        with patch('crm.import_views.fetch_order') as fetch:
            response=self.client.post('/tourvisor/import/',{'action':'lookup','order_id':old['id']})
            fetch.assert_not_called()
        self.assertContains(response,'2299358')
        contract=apply_order(self.order,self.user,set(GROUPS))
        self.assertEqual(contract.tourvisor_id,'2299358')

    def test_batch_marks_older_order_ineligible(self):
        batch=TourvisorBatch.objects.create(owner=self.user,expires_at=timezone.now()+timedelta(hours=1))
        old=copy.deepcopy(self.order);old['id']='2299357'
        row=TourvisorBatchRow.objects.create(batch=batch,source_id=old['id'],payload=old)
        result=summarize(row)
        self.assertFalse(result['eligible'])
        self.assertIn('2299358',result['error'])
