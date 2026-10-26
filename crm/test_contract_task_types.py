from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Customer,Operator,Contract,Task,TaskType,TaskTemplate
from .services import create_tasks,create_contract_tasks
from .card_forms import CardContractForm

class ContractTaskTypesTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','test@example.test','test-password');self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='Тестовый заказчик');self.operator=Operator.objects.create(name='ТО')
        self.contract=Contract.objects.create(customer=self.customer,operator=self.operator,date=date(2026,10,25),start=date(2026,11,10))
        self.kind=TaskType.objects.create(name='Договорная задача',description='Описание',for_contract=True)
        self.other=TaskType.objects.create(name='Только отдельная задача')
    def test_only_marked_types_and_date_rows_in_contract(self):
        form=CardContractForm(instance=self.contract)
        self.assertEqual(list(form.fields['task_templates'].queryset),[self.kind])
        self.assertEqual(form.fields[f'task_due_{self.kind.pk}'].initial,self.contract.date)
        response=self.client.get(f'/contracts/{self.contract.pk}/')
        self.assertContains(response,'Договорная задача');self.assertNotContains(response,f'name="task_templates" value="{self.other.pk}"')
        self.assertContains(response,'contract-task-row')
    def test_manual_save_creates_selected_type_and_preserves_import_task_rules(self):
        ignored=TaskTemplate.objects.create(name='Импортная задача',task_type=self.other,anchor='start',offset=-1)
        form=CardContractForm(instance=self.contract)
        response=self.client.post(f'/contracts/{self.contract.pk}/',{'action':'contract','version':form['version'].value(),'date':'2026-10-25','customer':self.customer.pk,'operator':self.operator.pk,'adults':0,'children':0,'infants':0,'source_currency':'RUB','task_templates':[self.kind.pk],f'task_due_{self.kind.pk}':'2026-11-05'})
        self.assertEqual(response.status_code,302)
        task=Task.objects.get(contract=self.contract);self.assertEqual(task.task_type,self.kind);self.assertEqual(task.description,'Описание');self.assertEqual(task.due,date(2026,11,5))
        create_contract_tasks(self.contract,[self.kind],{self.kind.pk:date(2026,11,6)})
        task.refresh_from_db();self.assertEqual(task.due,date(2026,11,5));self.assertEqual(Task.objects.count(),1)
        create_tasks(self.contract,[ignored])
        self.assertTrue(Task.objects.filter(contract=self.contract,task_type=self.other).exists())
    def test_existing_template_dates_and_exclusion_of_already_created(self):
        template=TaskTemplate.objects.create(name='Шаблон',task_type=self.kind,anchor='start',offset=-3)
        form=CardContractForm(instance=self.contract)
        self.assertEqual(form.fields[f'task_due_{self.kind.pk}'].initial,date(2026,11,7))
        create_contract_tasks(self.contract,[self.kind],{self.kind.pk:date(2026,11,8)})
        self.assertEqual(Task.objects.get().template,template)
        self.assertFalse(CardContractForm(instance=self.contract).fields['task_templates'].queryset.exists())
    def test_default_type_does_not_override_contract_checklist(self):
        self.kind.is_default=True;self.kind.save()
        response=self.client.get('/contracts/new/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Договорная задача')

    def test_unmarked_type_cannot_be_posted(self):
        form=CardContractForm(data={'task_templates':[self.other.pk]},instance=self.contract)
        self.assertFalse(form.is_valid());self.assertIn('task_templates',form.errors)

    def test_four_import_templates_ignore_contract_checkbox(self):
        from django.core.management import call_command
        call_command('seed_templates',verbosity=0)
        TaskType.objects.update(for_contract=False)
        self.contract.end=date(2026,11,20);self.contract.save()
        create_tasks(self.contract)
        self.assertEqual(Task.objects.filter(contract=self.contract).count(),4)
