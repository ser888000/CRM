from datetime import date,timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone
from .models import Customer,Operator,Contract,Task,TaskType,Payment,PaymentMethod

class CompactCardTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('compact','','password');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Проверочный заказчик')
        self.operator=Operator.objects.create(name='ТО')
        self.contract=Contract.objects.create(customer=self.customer,operator=self.operator)
        self.kind=TaskType.objects.create(name='Проверить документы')
        self.task=Task.objects.create(pk=36071,contract=self.contract,customer=self.customer,task_type=self.kind,title=self.kind.name,due=timezone.localdate())
    def test_high_id_task_save_and_split_money(self):
        method=PaymentMethod.objects.create(name='Касса')
        for kind in ['customer','customer_refund','operator','operator_refund']:
            Payment.objects.create(contract=self.contract,kind=kind,amount=100,method=method)
        url=f'/contracts/{self.contract.pk}/'
        response=self.client.get(url+'?tab=tasks')
        self.assertContains(response,'name="entry_id" value="36071"')
        self.assertNotContains(response,'Срок, ответственный и статус')
        self.assertNotContains(response,'Тип / название задачи')
        self.assertContains(response,'Запланировано')
        self.assertEqual([len(entries) for title,entries in response.context['payment_groups']],[2,2])
        response=self.client.post(url,{'action':'task','entry_id':'36071','task-36071-task_type':self.kind.pk,'task-36071-due':'2026-11-01','task-36071-done':'on'})
        self.assertEqual(response.status_code,302)
        self.task.refresh_from_db();self.assertTrue(self.task.done);self.assertEqual(self.task.due,date(2026,11,1))
    def test_reference_modal_create_edit_validation_and_permissions(self):
        response=self.client.post('/references/paymentmethod/new/',{'reference-name':'Новый способ'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.context['result']['text'],'Новый способ')
        method=PaymentMethod.objects.get(name='Новый способ')
        response=self.client.post(f'/references/paymentmethod/{method.pk}/',{'reference-name':'Изменённый способ'})
        method.refresh_from_db();self.assertEqual(method.name,'Изменённый способ')
        self.assertEqual(response.context['result']['id'],str(method.pk))
        self.assertEqual(self.client.get('/references/paymentmethod/resolve/',{'value':method.name}).json()['id'],str(method.pk))
        response=self.client.post('/references/paymentmethod/new/',{'reference-name':method.name})
        self.assertTrue(response.context['form'].errors)
        self.assertIsNone(response.context['result'])
        user=get_user_model().objects.create_user('limited',password='password')
        user.user_permissions.add(Permission.objects.get(codename='view_contract'))
        self.client.force_login(user)
        self.assertEqual(self.client.get('/references/paymentmethod/new/').status_code,403)
        self.assertEqual(self.client.post(f'/references/paymentmethod/{method.pk}/',{'reference-name':'Запрещено'}).status_code,403)
        self.assertEqual(self.client.get('/references/user/new/').status_code,404)
    def test_reference_dialog_supports_customer_passport_and_company_fields(self):
        response=self.client.get('/references/customer/new/')
        self.assertEqual(response.headers['X-Frame-Options'],'SAMEORIGIN')
        self.assertContains(response,'Юридическое лицо');self.assertContains(response,'crm/passport.js')
        self.assertNotContains(response,'data-reference-add=')
        response=self.client.post('/references/customer/new/',{'reference-kind':'person','reference-surname':'Иванов','reference-given_name':'Иван','reference-passport_type':'1'})
        self.assertEqual(response.context['result']['text'],'Иванов Иван')
    def test_fast_today_preserves_day_and_overdue_counts(self):
        today=timezone.localdate()
        Task.objects.bulk_create([Task(title='Старая история',due=today-timedelta(days=100),done=True) for _ in range(200)])
        Task.objects.create(title='Завтра выполнено',due=today+timedelta(days=1),done=True)
        Task.objects.create(title='Просрочено',due=today-timedelta(days=2))
        response=self.client.get('/tasks/?period=today')
        self.assertEqual(response.context['count'],1)
        self.assertEqual({t['key']:t['count'] for t in response.context['tabs']},{'today':1,'tomorrow':1})
        self.assertEqual({t['key']:t['count'] for t in response.context['status_tabs']}['overdue'],1)
