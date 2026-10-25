from datetime import date,timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Meal,PaymentMethod,Insurance,ContractType,TaskType,FuelSurcharge,Transfer,Task
from .widgets import LocationInput
from .card_forms import CardContractForm

class ReferenceSortTests(TestCase):
    def test_order_in_all_seven_directories_and_suggestions(self):
        for model in (Meal,PaymentMethod,Insurance,ContractType,TaskType,FuelSurcharge,Transfer):
            with self.subTest(model=model.__name__):
                model.objects.all().delete()
                for name,order in [('Яблоко',None),('Бета',None),('Альфа',20),('Юг',0),('Вега',20)]:model.objects.create(name=name,sort_order=order)
                expected=['Юг','Альфа','Вега','Бета','Яблоко']
                self.assertEqual(list(model.objects.values_list('name',flat=True)),expected)
                self.assertEqual(LocationInput(model).get_context('test',None,{'id':'test'})['widget']['suggestions'],expected)
    def test_contract_checklist_uses_type_order(self):
        TaskType.objects.create(name='Альфа',for_contract=True)
        first=TaskType.objects.create(name='Я первая',for_contract=True,sort_order=1)
        last=TaskType.objects.create(name='Я последняя',for_contract=True)
        form=CardContractForm()
        self.assertEqual([k.name for k in form.fields['task_templates'].queryset],['Я первая','Альфа','Я последняя'])
    def test_today_action_skips_completed_and_records_history(self):
        user=get_user_model().objects.create_superuser('test','test@example.test','test-password');self.client.force_login(user)
        today=date(2026,10,25)
        active=Task.objects.create(title='Сегодня',due=today+timedelta(days=5))
        done=Task.objects.create(title='Готово',due=today+timedelta(days=5),done=True)
        with patch('crm.task_views.timezone.localdate',return_value=today):
            self.client.post('/tasks/actions/',{'tasks':[active.pk,done.pk],'action':'today'})
        active.refresh_from_db();done.refresh_from_db()
        self.assertEqual(active.due,today);self.assertEqual(done.due,today+timedelta(days=5))
        from .models import AuditEvent
        self.assertEqual(AuditEvent.objects.get().action,'rescheduled')
