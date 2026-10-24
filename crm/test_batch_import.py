import copy
import json
from datetime import timedelta
from unittest.mock import patch,MagicMock
from django.test import TestCase,SimpleTestCase,Client
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from .models import Contract,Customer,Task,TaskTemplate,TourvisorBatch,TourvisorBatchRow
from .tourvisor import fetch_orders,TourvisorError,normalize_order,apply_order,GROUPS
from .test_tourvisor import sample

class BatchTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
        self.order=sample()
        self.second=copy.deepcopy(self.order);self.second['id']='2193762'
    def preview(self,entries=None):
        with patch('crm.batch_views.fetch_orders',return_value=entries if entries is not None else [self.order,self.second]):
            response=self.client.post('/tourvisor/batch/',{'limit':'25','lastid':''})
        self.assertEqual(response.status_code,302)
        batch=TourvisorBatch.objects.latest('created_at')
        self.url=f'/tourvisor/batch/{batch.pk}/';self.step=self.url+'step/'
        return batch
    def start(self,batch,rows=None,**extra):
        data={'selected':[str(r.pk) for r in (rows if rows is not None else batch.rows.all())]}
        for row in batch.rows.all():data['end_'+str(row.pk)]='2026-12-08';data['customer_'+str(row.pk)]='auto'
        data.update(extra)
        return self.client.post(self.url,data)
    def test_preview_and_each_step_create_only_one_then_reuse_customer(self):
        batch=self.preview();response=self.client.get(self.url)
        self.assertContains(response,'Новая');self.assertFalse(Contract.objects.exists())
        self.assertEqual(self.start(batch).status_code,302);self.assertFalse(Contract.objects.exists())
        response=self.client.post(self.step);self.assertEqual(response.status_code,200);self.assertEqual(Contract.objects.count(),1)
        self.assertFalse(response.json()['finished']);self.assertEqual(response.json()['counts']['queued'],1)
        response=self.client.post(self.step);self.assertTrue(response.json()['finished']);self.assertEqual(Contract.objects.count(),2)
        self.assertEqual(Customer.objects.count(),1)
        self.assertFalse(batch.rows.exclude(payload={}).exists())
        self.assertEqual(self.client.post(self.step).status_code,409);self.assertEqual(Contract.objects.count(),2)
        self.assertContains(self.client.get(self.url),'Создан')
    def test_known_contract_status_and_cannot_select_for_update(self):
        c=apply_order(self.order,self.user,set(GROUPS));other=copy.deepcopy(self.order);other['price']='210000'
        batch=self.preview([other,self.second]);response=self.client.get(self.url)
        self.assertContains(response,'Есть изменения')
        self.assertEqual(self.start(batch).status_code,200)
        self.assertEqual(self.c_amount(c),200000)
        self.assertEqual(self.start(batch,[batch.rows.get(source_id=self.second['id'])]).status_code,302)
        self.client.post(self.step);self.assertEqual(self.c_amount(c),200000)
    def c_amount(self,c):c.refresh_from_db();return c.amount
    def test_one_bad_order_does_not_prevent_other_rows(self):
        bad=copy.deepcopy(self.order);bad['price']='invalid'
        batch=self.preview([bad,self.second]);response=self.client.get(self.url)
        self.assertContains(response,'некорректные данные')
        row=batch.rows.get(source_id=self.second['id'])
        self.assertEqual(self.start(batch,[row]).status_code,302)
        self.assertTrue(self.client.post(self.step).json()['finished']);self.assertEqual(Contract.objects.count(),1)
    def test_error_during_one_import_does_not_rollback_completed_contract(self):
        batch=self.preview();self.start(batch)
        with patch('crm.batch_views.apply_order',side_effect=TourvisorError('Проверка заявки не пройдена')):
            r=self.client.post(self.step)
        self.assertEqual(r.json()['counts']['error'],1);self.assertEqual(r.json()['counts']['queued'],1)
        self.client.post(self.step);self.assertEqual(Contract.objects.count(),1)
        error=batch.rows.get(state='error');self.assertTrue(error.payload)
        self.assertEqual(self.start(batch,[error]).status_code,302)
        self.client.post(self.step);self.assertEqual(Contract.objects.count(),2)
    def test_end_and_customer_resolution_required_and_tasks_scoped(self):
        n=normalize_order(self.order)
        Customer.objects.create(**{**n['customer'],'main_phone':'79990000000','main_email':'different@example.test'})
        batch=self.preview([self.order]);row=batch.rows.get()
        template=TaskTemplate.objects.create(name='После поездки',anchor='end',offset=2)
        data={'selected':[row.pk],'end_'+str(row.pk):'','customer_'+str(row.pk):'','templates':[template.pk]}
        response=self.client.post(self.url,data)
        self.assertContains(response,'Подтвердите дату окончания');self.assertFalse(Contract.objects.exists())
        data['end_'+str(row.pk)]='2026-12-08';data['customer_'+str(row.pk)]='new';data[f'due_{row.pk}_{template.pk}']='2026-12-12'
        self.assertEqual(self.client.post(self.url,data).status_code,302);self.client.post(self.step)
        self.assertEqual(str(Task.objects.get().due),'2026-12-12');self.assertEqual(Customer.objects.count(),2)
    def test_contract_created_after_preview_is_not_duplicated_or_updated(self):
        batch=self.preview([self.order]);self.start(batch)
        c=apply_order(self.order,self.user,set(GROUPS));c.notes='Сохранить';c.save()
        response=self.client.post(self.step)
        self.assertTrue(response.json()['finished']);self.assertEqual(Contract.objects.count(),1)
        c.refresh_from_db();self.assertEqual(c.notes,'Сохранить')
    def test_expiry_clears_snapshots_and_cannot_start_or_step(self):
        batch=self.preview([self.order]);self.start(batch)
        batch.expires_at=timezone.now()-timedelta(seconds=1);batch.save()
        self.assertEqual(self.client.post(self.step).status_code,410)
        self.assertEqual(batch.rows.get().payload,{})
        self.assertContains(self.client.get(self.url),'Предпросмотр устарел');self.assertFalse(Contract.objects.exists())
    def test_permissions_owner_scope_and_csrf(self):
        batch=self.preview([self.order]);self.start(batch)
        other=get_user_model().objects.create_superuser('other','other@example.test','test-password-456');self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code,404);self.assertEqual(self.client.post(self.step).status_code,404)
        limited=get_user_model().objects.create_user('limited');self.client.force_login(limited)
        self.assertEqual(self.client.get('/tourvisor/batch/').status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post(self.step).status_code,403)
    def test_no_get_mutation_and_step_before_start_rejected(self):
        self.preview([self.order]);self.assertEqual(self.client.get(self.step).status_code,405)
        self.assertEqual(self.client.post(self.step).status_code,409);self.assertFalse(Contract.objects.exists())
    def test_fetch_error_sanitized_and_no_draft_saved(self):
        with patch('crm.batch_views.fetch_orders',side_effect=TourvisorError('Турвизор временно недоступен')):
            response=self.client.post('/tourvisor/batch/',{'limit':'25'})
        self.assertContains(response,'временно недоступен');self.assertFalse(TourvisorBatch.objects.exists())
    def test_cleanup_expired_only_preserves_created_contracts(self):
        batch=self.preview([self.order]);self.start(batch);self.client.post(self.step)
        old=TourvisorBatch.objects.create(owner=self.user,expires_at=timezone.now()-timedelta(minutes=1))
        row=TourvisorBatchRow.objects.create(batch=old,source_id='999',payload={'private':'remove'},plan={'end':'2026-12-08'})
        call_command('purge_tourvisor_batches',verbosity=0)
        row.refresh_from_db();self.assertEqual(row.payload,{});self.assertEqual(row.plan,{})
        self.assertEqual(Contract.objects.count(),1)

class BatchClientTests(SimpleTestCase):
    def request(self,data):
        mock=MagicMock();mock.open.return_value.__enter__.return_value.read.return_value=json.dumps(data).encode()
        return mock
    def test_list_accepts_single_empty_and_multiple_and_uses_documented_parameters(self):
        for entries,expected in [([],0),({'id':'12'},1),([{'id':'12'},{'id':'13'}],2)]:
            mock=self.request({'orders':{'order':entries}})
            with patch.dict('os.environ',{'TOURVISOR_API_KEY':'TEST-SECRET'}),patch('crm.tourvisor.request.build_opener',return_value=mock):
                rows=fetch_orders(25,'10');self.assertEqual(len(rows),expected)
                url=mock.open.call_args.args[0];self.assertIn('limit=25',url);self.assertIn('lastid=10',url);self.assertNotIn('orders.php?',url)
    def test_duplicate_ids_bad_shape_and_limits_rejected(self):
        for entries in [[{'id':'12'},{'id':'12'}],[{'id':'wrong'}],['unexpected']]:
            with patch.dict('os.environ',{'TOURVISOR_API_KEY':'TEST-SECRET'}),patch('crm.tourvisor.request.build_opener',return_value=self.request({'orders':{'order':entries}})):
                with self.assertRaises(TourvisorError):fetch_orders()
        with self.assertRaises(TourvisorError):fetch_orders(500)
        with self.assertRaises(TourvisorError):fetch_orders(25,'not numeric')
