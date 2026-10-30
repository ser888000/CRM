from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from .models import Customer,Operator,Contract,Task,TaskType,PaymentMethod,EmployeeVisibility
from .task_views import TaskEditorForm
from .forms import ContractForm

class TaskTuningTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('tuning','','password');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Тестовый заказчик',main_phone='+70000000000',main_email='test@example.test')
        self.operator=Operator.objects.create(name='ТО',booking_url_template='https://example.test/{booking}')
        self.contract=Contract.objects.create(number='D-1',customer=self.customer,operator=self.operator)
        self.task=Task.objects.create(pk=36071,title='Позвонить',due=date.today(),customer=self.customer,contract=self.contract,booking_number='ABC')
    def test_high_ids_contacts_and_booking_links(self):
        response=self.client.get('/tasks/?period=all')
        self.assertContains(response,'name="tasks" value="36071"')
        self.assertContains(response,f'href="/customers/{self.customer.pk}/"')
        self.assertContains(response,'Телефон / e-mail');self.assertContains(response,self.customer.main_phone)
        self.client.post('/tasks/actions/',{'tasks':'36071','action':'complete'})
        self.task.refresh_from_db();self.assertTrue(self.task.done)
        self.client.post('/tasks/actions/',{'tasks':'36071','action':'reschedule','quick_action':'today'})
        response=self.client.get('/tasks/36071/')
        self.assertContains(response,'email заказчика');self.assertContains(response,'https://example.test/ABC')
        self.assertContains(response,'id="id_task_type"',count=1)
        self.assertContains(response,'<select name="task_type"')
        self.assertEqual(self.client.get('/tasks/booking/',{'contract':self.contract.pk,'number':'NEW'}).json()['bookings'][0]['url'],'https://example.test/NEW')
    def test_reference_archive_retains_saved_values(self):
        method=PaymentMethod.objects.create(name='Устаревший',is_hidden=True,is_default=True)
        self.contract.payment_method=method;self.contract.save()
        self.assertNotIn(method,list(ContractForm().fields['payment_method'].queryset))
        self.assertIn(method,list(ContractForm(instance=self.contract).fields['payment_method'].queryset))
        kind=TaskType.objects.create(name='Архив',is_hidden=True)
        self.task.task_type=kind;self.task.title=kind.name;self.task.save()
        self.assertIn(kind,list(TaskEditorForm(instance=self.task).fields['task_type'].queryset))
        self.assertNotIn(kind,list(TaskEditorForm().fields['task_type'].queryset))
        EmployeeVisibility.objects.create(user=self.user,is_hidden=True)
        self.assertNotIn(self.user,list(TaskEditorForm().fields['employee'].queryset))
        self.task.employee=self.user;self.task.save()
        self.assertIn(self.user,list(TaskEditorForm(instance=self.task).fields['employee'].queryset))
        self.user.refresh_from_db();self.assertTrue(self.user.is_active)
    def test_related_query_count_does_not_grow_per_task(self):
        Task.objects.bulk_create([Task(title='Ещё',due=date.today(),customer=self.customer,contract=self.contract) for _ in range(80)])
        with CaptureQueriesContext(connection) as queries:response=self.client.get('/tasks/?period=all')
        self.assertEqual(response.context['count'],81)
        self.assertLess(len(queries),35)
    def test_lookup_is_bounded_and_hidden_choices_excluded(self):
        Customer.objects.create(name='Тест скрытый',is_hidden=True)
        values=self.client.get('/tasks/choices/customers/',{'q':'тест'}).json()['choices']
        self.assertEqual([v['id'] for v in values],[self.customer.pk])
        form=TaskEditorForm(instance=self.task)
        self.assertEqual(len(form.fields['customer'].widget.choices),2)

    def test_many_column_choices_are_bounded_and_searchable(self):
        Task.objects.bulk_create([Task(title=f'Тест {n:04d}',due=date.today()) for n in range(150)])
        response=self.client.get('/tasks/?period=all')
        column=next(c for c in response.context['columns'] if c['key']=='title')
        self.assertTrue(column['remote']);self.assertLessEqual(len(column['options']),100)
        values=self.client.get('/tasks/',{'period':'all','choice_column':'title','choice_search':'0149'}).json()['values']
        self.assertEqual(values,['Тест 0149'])
