from datetime import date,timedelta
from unittest.mock import patch
from django.test import TestCase,Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from .models import Task,Customer,Contract,Operator,TaskTemplate,AuditEvent

class TaskWorkspaceTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
        self.today=date(2026,10,24)
        self.customer=Customer.objects.create(name='Петров Иван');self.operator=Operator.objects.create(name='Тестовый ТО')
        self.contract=Contract.objects.create(customer=self.customer,operator=self.operator,number='TEST-1')
        self.old=Task.objects.create(title='Проверить вылет',description='Рейс TEST123',due=self.today-timedelta(days=1),contract=self.contract,customer=self.customer)
        self.current=Task.objects.create(title='Выслать документы',due=self.today)
        self.done=Task.objects.create(title='Позвонить',due=self.today,done=True)
    def test_period_counts_unicode_filters_and_context_restore(self):
        with patch('crm.task_views.timezone.localdate',return_value=self.today):
            r=self.client.get('/tasks/?period=all')
            self.assertEqual(r.context['count'],3)
            counts={tab['key']:tab['count'] for tab in r.context['tabs']};self.assertEqual(counts['today'],2);self.assertEqual({tab['key']:tab['count'] for tab in r.context['status_tabs']}['overdue'],1)
            r=self.client.get('/tasks/',{'period':'all','q':'test123','customer':'пЕтРоВ','number':'test-1'})
            self.assertEqual([t.pk for t in r.context['rows']],[self.old.pk])
            self.client.get('/finances/')
            self.assertEqual(self.client.get('/tasks/',follow=True).context['count'],1)
            self.assertEqual(self.client.get('/tasks/?reset=1',follow=True).context['period'],'all')
    def test_complete_reopen_and_reschedule_preserve_context_and_audit(self):
        target='/tasks/actions/'
        r=self.client.post(target,{'tasks':[self.old.pk,self.current.pk],'action':'complete','return_query':'period=all&q=TEST'})
        self.assertEqual(r.url,'/tasks/?period=all&q=TEST');self.old.refresh_from_db();self.assertTrue(self.old.done)
        self.client.post(target,{'tasks':[self.old.pk],'action':'reopen'})
        self.old.refresh_from_db();self.assertFalse(self.old.done)
        self.client.post(target,{'tasks':[self.old.pk,self.done.pk],'action':'reschedule','due':'2026-11-01'})
        self.old.refresh_from_db();self.done.refresh_from_db()
        self.assertEqual(self.old.due,date(2026,11,1));self.assertEqual(self.done.due,self.today)
        self.assertEqual(AuditEvent.objects.filter(object_type='crm.Task',object_id=str(self.old.pk)).count(),3)
    def test_invalid_bulk_request_does_not_mutate(self):
        for data in [{'tasks':[self.old.pk],'action':'reschedule','due':'bad'}, {'tasks':['bad'],'action':'complete'}, {'action':'complete'}, {'tasks':[self.old.pk],'action':'delete'}]:
            self.assertEqual(self.client.post('/tasks/actions/',data).status_code,302)
        self.old.refresh_from_db();self.assertEqual(self.old.due,self.today-timedelta(days=1));self.assertFalse(self.old.done)
    def test_editor_create_without_contract_and_immediate_monthly_repeats(self):
        r=self.client.post('/tasks/new/',{'title':'Проверка','description':'Напоминание','due':'2026-01-31','repeat':'month','occurrences':3,'return_query':'period=all'})
        self.assertEqual(r.status_code,302)
        self.assertEqual(list(Task.objects.filter(title='Проверка').order_by('due').values_list('due',flat=True)),[date(2026,1,31),date(2026,2,28),date(2026,3,31)])
    def test_contract_customer_alignment_and_conflict(self):
        data={'title':'По договору','due':'2026-11-01','contract':self.contract.pk}
        r=self.client.post('/tasks/new/',data);self.assertEqual(r.status_code,302)
        self.assertEqual(Task.objects.get(title='По договору').customer_id,self.customer.pk)
        other=Customer.objects.create(name='Другой');data.update(title='Ошибка',customer=other.pk)
        self.assertEqual(self.client.post('/tasks/new/',data).status_code,200);self.assertFalse(Task.objects.filter(title='Ошибка').exists())
    def test_stale_editor_and_template_link_protected(self):
        url=f'/tasks/{self.old.pk}/';response=self.client.get(url);version=response.context['form']['version'].value()
        self.old.done=True;self.old.save()
        response=self.client.post(url,{'title':'Правка','due':'2026-11-01','version':version})
        self.assertContains(response,'изменена в другом окне');self.old.refresh_from_db();self.assertEqual(self.old.title,'Проверить вылет')
        self.old.origin_key=f'contract:{self.contract.pk}:template:1';self.old.save()
        other=Contract.objects.create(customer=self.customer,operator=self.operator)
        form=self.client.get(url).context['form'];data={'title':self.old.title,'due':'2026-11-01','version':form['version'].value(),'contract':other.pk}
        self.assertEqual(self.client.post(url,data).status_code,302);self.old.refresh_from_db();self.assertEqual(self.old.contract_id,self.contract.pk)
    def test_repeat_overflow_rolls_back_first_task(self):
        response=self.client.post('/tasks/new/',{'title':'Недопустимая серия','due':'9999-12-31','repeat':'year','occurrences':2})
        self.assertEqual(response.status_code,200);self.assertFalse(Task.objects.filter(title='Недопустимая серия').exists())
    def test_permissions_and_csrf(self):
        viewer=get_user_model().objects.create_user('viewer');viewer.user_permissions.add(Permission.objects.get(codename='view_task'));self.client.force_login(viewer)
        response=self.client.get('/tasks/?period=all');self.assertEqual(response.status_code,200);self.assertNotContains(response,'id="task-action"')
        self.assertEqual(self.client.post('/tasks/actions/',{'action':'complete','tasks':[self.old.pk]}).status_code,403)
        self.assertEqual(self.client.get('/tasks/new/').status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post('/tasks/actions/',{'action':'complete','tasks':[self.old.pk]}).status_code,403)
    def test_continuous_list_accepts_legacy_page_links(self):
        Task.objects.bulk_create([Task(title='Много задач',due=self.today) for _ in range(105)])
        response=self.client.get('/tasks/?period=all&page=2')
        self.assertEqual(response.context['count'],108);self.assertEqual(len(response.context['rows']),108)
        self.assertIn('page=2',response.context['return_query'])
        self.assertNotIn('page=',response.context['tabs'][0]['url'])
    def test_redirect_cannot_escape_task_journal(self):
        response=self.client.post('/tasks/actions/',{'action':'complete','tasks':[self.current.pk],'return_query':'next=https://example.test&foo=bar&period=all'})
        self.assertEqual(response.url,'/tasks/?period=all')

    def test_dates_status_and_overdue_are_independent(self):
        tomorrow=Task.objects.create(title='Завтра готово',due=self.today+timedelta(days=1),done=True)
        with patch('crm.task_views.timezone.localdate',return_value=self.today):
            response=self.client.get('/tasks/?period=today')
            self.assertEqual({t.pk for t in response.context['rows']},{self.current.pk,self.done.pk})
            response=self.client.get('/tasks/?period=today&status=planned')
            self.assertEqual([t.pk for t in response.context['rows']],[self.current.pk])
            response=self.client.get('/tasks/?period=tomorrow')
            self.assertEqual([t.pk for t in response.context['rows']],[tomorrow.pk])
            response=self.client.get('/tasks/?period=overdue&status=done&start=2030-01-01&end=2030-01-01')
            self.assertEqual([t.pk for t in response.context['rows']],[self.old.pk])
            response=self.client.get('/tasks/?period=custom&status=done&start=2026-10-24&end=2026-10-25')
            self.assertEqual({t.pk for t in response.context['rows']},{self.done.pk,tomorrow.pk})
    def test_column_filters_sort_and_tomorrow_action(self):
        response=self.client.get('/tasks/',{'period':'all','sort':'-due','f_title':[self.old.title,self.current.title]})
        self.assertEqual([t.pk for t in response.context['rows']],[self.current.pk,self.old.pk])
        self.assertContains(response,'Фильтр: Сотрудник')
        self.assertNotContains(response,'Найдено задач:')
        with patch('crm.task_views.timezone.localdate',return_value=self.today):
            self.client.post('/tasks/actions/',{'tasks':[self.old.pk,self.done.pk],'action':'tomorrow'})
        self.old.refresh_from_db();self.done.refresh_from_db()
        self.assertEqual(self.old.due,self.today+timedelta(days=1));self.assertEqual(self.done.due,self.today)
    def test_task_type_name_description_and_rename(self):
        from .models import TaskType
        kind=TaskType.objects.create(name='Короткое имя',description='Описание типа')
        response=self.client.post('/tasks/new/',{'task_type':kind.pk,'due':'2026-11-01'})
        self.assertEqual(response.status_code,302)
        task=Task.objects.get(task_type=kind);self.assertEqual(task.description,kind.description)
        kind.name='Новое имя';kind.save()
        response=self.client.get('/tasks/?period=all')
        self.assertContains(response,'Новое имя')

    def test_filter_rows_and_status_order(self):
        response=self.client.get('/tasks/?period=all')
        self.assertEqual(list(response.context['filters'].fields),['q','customer','employee','start','end'])
        self.assertEqual([t['label'] for t in response.context['tabs']],['Сегодня','Завтра'])
        self.assertEqual([t['label'] for t in response.context['status_tabs']],['Все','Запланировано','Выполнено','Просрочено'])
        with patch('crm.task_views.timezone.localdate',return_value=self.today):
            response=self.client.get('/tasks/?period=today&status=overdue')
            self.assertEqual([t.pk for t in response.context['rows']],[self.old.pk])
            links={tab['key']:tab['url'] for tab in response.context['status_tabs']}
            response=self.client.get('/tasks/'+links['all'])
            self.assertEqual({t.pk for t in response.context['rows']},{self.current.pk,self.done.pk})
