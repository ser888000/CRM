from datetime import date
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from .models import ContractType,PaymentMethod,Currency,Contract,Booking,Customer,Operator,AuditEvent,Task
from .tourvisor import apply_order,GROUPS
from .test_tourvisor import sample


class ImportDefaultsAndBookingsTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('defaults-owner',password='test')
        self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Тест')
        self.operator=Operator.objects.create(name='Тест ТО')
        self.contract=Contract.objects.create(number='manual',customer=self.customer,operator=self.operator)

    def test_import_sets_reference_defaults_and_refresh_preserves_manual_choices(self):
        kind=ContractType.objects.create(name='Тип по умолчанию',is_default=True)
        method=PaymentMethod.objects.create(name='Способ по умолчанию',is_default=True)
        Currency.objects.update_or_create(code='USD',defaults={'name':'Доллар','is_default':True,'is_hidden':False})
        order=sample(); contract=apply_order(order,self.user,set(GROUPS))
        self.assertEqual((contract.contract_type_id,contract.payment_method_id,contract.source_currency),(kind.pk,method.pk,'USD'))
        other_kind=ContractType.objects.create(name='Другой тип')
        other_method=PaymentMethod.objects.create(name='Другой способ')
        contract.contract_type=other_kind;contract.payment_method=other_method;contract.source_currency='EUR';contract.save()
        refreshed=apply_order(order,self.user,{'tour'},expected=contract.pk)
        self.assertEqual((refreshed.contract_type_id,refreshed.payment_method_id,refreshed.source_currency),(other_kind.pk,other_method.pk,'EUR'))

    def test_hidden_defaults_not_applied(self):
        ContractType.objects.create(name='Скрытый',is_default=True,is_hidden=True)
        PaymentMethod.objects.create(name='Скрытый',is_default=True,is_hidden=True)
        Currency.objects.update_or_create(code='USD',defaults={'name':'Доллар','is_default':True,'is_hidden':True})
        contract=apply_order(sample(),self.user,set(GROUPS))
        self.assertIsNone(contract.contract_type_id);self.assertIsNone(contract.payment_method_id)
        self.assertEqual(contract.source_currency,'RUB')

    def test_booking_delete_scoped_versioned_audited_and_requires_permission(self):
        booking=Booking.objects.create(contract=self.contract,number='TEST-BOOKING')
        url=reverse('contract_card',args=[self.contract.pk])
        payload={'action':'delete_booking','entry_id':booking.pk,'version':str(self.contract.updated_at)}
        response=self.client.post(url,payload)
        self.assertRedirects(response,url+'?tab=bookings')
        self.assertFalse(Booking.objects.filter(pk=booking.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(object_type='crm.Booking',action='deleted',object_id=str(booking.pk)).exists())
        other=Contract.objects.create(number='other',customer=self.customer,operator=self.operator)
        foreign=Booking.objects.create(contract=other,number='FOREIGN')
        payload['entry_id']=foreign.pk
        self.assertEqual(self.client.post(url,payload).status_code,404)
        self.assertTrue(Booking.objects.filter(pk=foreign.pk).exists())
        user=get_user_model().objects.create_user('read-only')
        user.user_permissions.add(Permission.objects.get(codename='view_contract'))
        self.client.force_login(user)
        self.assertEqual(self.client.post(url,payload).status_code,403)

    def test_stale_booking_delete_preserves_booking(self):
        booking=Booking.objects.create(contract=self.contract,number='STALE')
        self.client.post(reverse('contract_card',args=[self.contract.pk]),{'action':'delete_booking','entry_id':booking.pk,'version':'stale'})
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())

    def test_deadline_is_inside_finances_only_and_posts_return_there(self):
        url=reverse('contract_card',args=[self.contract.pk])
        response=self.client.get(url)
        html=response.content.decode()
        self.assertLess(html.index('data-panel="finance"'),html.index('До какого числа оплатить ТО'))
        self.assertNotIn('operator_due',html.split('data-panel="bookings"',1)[1].split('data-panel="finance"',1)[0])
        response=self.client.post(url,{'action':'operator_due','version':str(self.contract.updated_at),'due':'2026-12-01'})
        self.assertRedirects(response,url+'?tab=finance')
        self.contract.refresh_from_db();self.assertEqual(self.contract.operator_due,date(2026,12,1))

    def test_task_done_uses_hidden_field_and_button_and_saves_both_states(self):
        from .task_views import version
        task=Task.objects.create(title='Тестовая задача',customer=self.customer,due=date(2026,12,1))
        url=reverse('task_editor',args=[task.pk])
        response=self.client.get(url)
        self.assertContains(response,'data-task-done="id_done"')
        self.assertContains(response,'type="hidden" name="done"')
        for value,expected in [('1',True),('0',False)]:
            response=self.client.post(url,{'title':task.title,'customer':self.customer.pk,'due':'2026-12-01','done':value,'version':version(task)})
            self.assertEqual(response.status_code,302)
            task.refresh_from_db();self.assertEqual(task.done,expected)
