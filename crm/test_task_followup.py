import importlib
from datetime import date
from types import SimpleNamespace
from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from .models import Customer,Operator,Contract,ContractLine,Tourist,Task,TaskType,LegacyRecord
from .task_views import TaskEditorForm
from .card_forms import TaskCardForm
from .legacy_history import load_history,apply_history
from .test_legacy_history import fixture,package

class FollowupTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('followup','','password');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Тестовый Иван',birthday=date(1980,1,2),main_phone='+79990000000')
        self.operator=Operator.objects.create(name='ТО')
        self.contract=Contract.objects.create(number='TEST',customer=self.customer,operator=self.operator)
    def test_unlink_tourist_preserves_catalog_other_contract_and_cost(self):
        tourist=Tourist.objects.create(name='TEST TOURIST')
        first=ContractLine.objects.create(pk=12001,contract=self.contract,tourist=tourist,description='Тур',amount=100,tourist_snapshot={'name':'TEST TOURIST'})
        other=Contract.objects.create(customer=self.customer,operator=self.operator)
        shared=ContractLine.objects.create(contract=other,tourist=tourist,amount=200)
        response=self.client.post(f'/contracts/{self.contract.pk}/',{'delete_action':'delete_tourist','entry_id':tourist.pk,'line_id':'12001'})
        self.assertEqual(response.status_code,302);first.refresh_from_db();shared.refresh_from_db()
        self.assertIsNone(first.tourist_id);self.assertEqual(first.tourist_snapshot,{})
        self.assertEqual(first.amount,100);self.assertEqual(shared.tourist_id,tourist.pk);self.assertTrue(Tourist.objects.filter(pk=tourist.pk).exists())
        self.assertEqual(self.client.post(f'/contracts/{self.contract.pk}/',{'delete_action':'delete_line','entry_id':shared.pk}).status_code,404)
        self.assertEqual(self.client.post(f'/contracts/{self.contract.pk}/',{'delete_action':'delete_line','entry_id':'12001'}).status_code,302)
        self.assertFalse(ContractLine.objects.filter(pk=12001).exists());self.assertEqual(self.contract.amount,0)
    def test_deletion_requires_specific_permission(self):
        line=ContractLine.objects.create(contract=self.contract,amount=100)
        user=get_user_model().objects.create_user('reader',password='password');user.user_permissions.add(Permission.objects.get(codename='view_contract'));self.client.force_login(user)
        self.assertEqual(self.client.post(f'/contracts/{self.contract.pk}/',{'delete_action':'delete_line','entry_id':line.pk}).status_code,403)
        self.assertTrue(ContractLine.objects.filter(pk=line.pk).exists())
    def test_form_order_lookup_identity_and_journal_links(self):
        kind=TaskType.objects.create(name='Позвонить')
        task=Task.objects.create(title=kind.name,task_type=kind,customer=self.customer,contract=self.contract,due=date.today(),result='Согласовано')
        fields=[f.name for f in TaskEditorForm() if not f.is_hidden]
        self.assertEqual(fields[:8],['task_type','due','employee','description','result','done','customer','contract'])
        self.assertEqual(list(TaskCardForm().fields),['task_type','due','done','description','result','employee'])
        values=self.client.get('/tasks/choices/customers/',{'q':'ивАН'}).json()['choices']
        self.assertIn('02.01.1980',values[0]['label']);self.assertIn('+79990000000',values[0]['label'])
        page=self.client.get('/tasks/?period=all')
        self.assertContains(page,'data-reference-open=');self.assertContains(page,f'href="/contracts/{self.contract.pk}/?tab=tasks">');self.assertContains(page,'Согласовано')
        page=self.client.get(f'/contracts/{self.contract.pk}/?tab=tasks')
        self.assertContains(page,'href="#contract-new-task"');self.assertContains(page,'id="contract-new-task"')
    def test_import_and_upgrade_split_results_without_overwriting_manual_description(self):
        raw=fixture();data=load_history(package(raw));apply_history(data)
        record=LegacyRecord.objects.filter(table='LIST_CONTACT_COMPANY').first();task=Task.objects.get(pk=record.target_id)
        self.assertEqual(task.description,'Описание');self.assertEqual(task.result,'Результат')
        task.result='';task.description='Описание\n\nРезультат: Результат';task.save()
        migration=importlib.import_module('crm.migrations.0033_task_result')
        migration.transfer_results(apps,SimpleNamespace(connection=connection))
        task.refresh_from_db();self.assertEqual((task.description,task.result),('Описание','Результат'))
        task.result='';task.description='Моя новая заметка';task.save()
        migration.transfer_results(apps,SimpleNamespace(connection=connection));task.refresh_from_db()
        self.assertEqual((task.description,task.result),('Моя новая заметка','Результат'))
