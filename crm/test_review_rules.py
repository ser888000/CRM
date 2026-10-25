from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase,RequestFactory
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.http import QueryDict
from django.db import connection
from django.test.utils import CaptureQueriesContext
from . import models as m
from .legacy_history import load_history,apply_history
from .legacy_reset import replace_history
from .test_legacy_history import fixture,package

class ReviewRulesTests(TestCase):
    def data(self):
        raw=fixture();raw['format']='aborigen-legacy-history-v2'
        raw['tables']['PRIZNAK_DOCUMENTS']=[{'ID_PRIZNAK_DOCUMENT':1,'PRIZNAK_DOCUMENT':'Интернет'}]
        raw['tables']['LIST_DOCUMENTS'][0].update(ID_PRIZNZK_DOC=1,ADD_DOC_COUNTRY='Тайланд',ADD_BIG_PUTESHESTVIYA='Кемерово/Новосибирск',ADD_MESTO_PUTESHESTVIYA='Пхукет',ADD_PRODOLZHITELNOCT='14 ночей',ADD_DATE_OPLATY_TO='2020-01-07')
        return load_history(package(raw))
    def login(self):
        user=get_user_model().objects.create_user('review-admin',is_staff=True,is_superuser=True);self.client.force_login(user);return user
    def test_import_source_rules_and_tourist_reuse(self):
        data=self.data();row=data['indexes']['LIST_TOVAR_DOC'][30].copy();row['ID_TOVAR_DOC']=31;data['indexes']['LIST_TOVAR_DOC'][31]=row
        run,_=apply_history(data);contract=m.Contract.objects.get(number='A-10')
        self.assertEqual((contract.departure,contract.region,contract.nights,contract.country),('Кемерово','Пхукет',14,'Таиланд'))
        self.assertEqual(contract.payment_method.name,'Тинькофф Интернет')
        p=m.Payment.objects.get(kind='operator');self.assertEqual(p.method.name,'Тинькофф р/с');self.assertEqual(str(p.date),'2020-01-07')
        self.assertEqual(contract.cost,200);self.assertEqual(contract.opening_operator_paid,0)
        self.assertEqual(m.Tourist.objects.count(),1);self.assertEqual(len(set(contract.lines.values_list('tourist_id',flat=True))),1)
        self.assertEqual(contract.amount,500)
    def test_reset_preserves_exceptions_and_rolls_back_failure(self):
        self.login();apply_history(self.data())
        kind=m.TaskType.objects.create(name='Сохранённый тип',for_contract=True)
        template=m.TaskTemplate.objects.create(name='Сохранённый шаблон',anchor='start',task_type=kind)
        library=m.LibraryEntry.objects.create(title='Библиотека',body='Сохранить')
        city=m.DepartureCity.objects.create(name='Город',code='CITY-TEST');country=m.Country.objects.create(name='Страна',code='COUNTRY-TEST')
        currency=m.Currency.objects.first();operation=m.PaymentOperation.objects.first()
        old_contract=list(m.Contract.objects.values_list('pk',flat=True))
        with patch('crm.legacy_reset.apply_history',side_effect=RuntimeError('simulated')):
            with self.assertRaises(RuntimeError):replace_history(self.data())
        self.assertEqual(list(m.Contract.objects.values_list('pk',flat=True)),old_contract)
        run,_=replace_history(self.data())
        self.assertFalse(m.Contract.objects.filter(pk__in=old_contract).exists())
        self.assertTrue(m.LibraryEntry.objects.filter(pk=library.pk).exists());self.assertTrue(m.DepartureCity.objects.filter(pk=city.pk).exists());self.assertTrue(m.Country.objects.filter(pk=country.pk).exists())
        template.refresh_from_db();self.assertIsNotNone(template.task_type_id)
        self.assertTrue(m.Currency.objects.filter(pk=currency.pk).exists());self.assertTrue(m.PaymentOperation.objects.filter(pk=operation.pk).exists())
        self.assertEqual(m.Customer.objects.count(),2);self.assertTrue(run.summary['replaced_training'])
        self.assertFalse(get_user_model().objects.filter(username__startswith='legacy_',is_active=True).exists())
    def test_search_ignores_dates_and_reset_restores_period(self):
        apply_history(self.data());self.login()
        for url,query in [('/',{'customer':'Примеров'}),('/finances/',{'number':'A-10'}),('/tasks/',{'customer':'Примеров'})]:
            response=self.client.get(url,{**query,'period':'custom','start':'2030-01-01','end':'2030-01-02'})
            self.assertEqual(response.status_code,200);self.assertTrue(response.context['search_all_dates']);self.assertGreater(response.context['count'],0)
            response=self.client.get(response.context['reset_filters_url'],follow=True)
            self.assertEqual(response.status_code,200);self.assertEqual(response.context['count'],0)
            self.assertFalse(response.context['search_all_dates'])
    def test_shared_customer_tasks_visible_and_not_reassigned(self):
        apply_history(self.data());self.login();contract=m.Contract.objects.exclude(number='A-10').get()
        response=self.client.get(f'/contracts/{contract.pk}/?tab=tasks')
        self.assertEqual(response.context['task_count'],2);self.assertContains(response,'без привязки к конкретному договору')
        task=m.Task.objects.filter(done=True).first();form=response.context['tasks'][0].edit_form
        self.assertIsNone(task.contract_id)
        # Visibility must not manufacture a contract link during GET.
        task.refresh_from_db();self.assertIsNone(task.contract_id)
    def test_admin_financials_bounded_queries(self):
        apply_history(self.data());user=self.login()
        from .admin import ContractAdmin
        request=RequestFactory().get('/admin/crm/contract/');request.user=user
        admin_model=ContractAdmin(m.Contract,admin.site)
        with CaptureQueriesContext(connection) as captured:
            rows=list(admin_model.get_queryset(request))
            values=[(r.amount,r.paid,r.cost,r.profit) for r in rows]
        self.assertLessEqual(len(captured),2);self.assertEqual(values[0][0],Decimal('500'))
    def test_customer_column_choices_are_bounded_and_searchable(self):
        self.login()
        m.Customer.objects.bulk_create([m.Customer(name=f'Заказчик {n:04d}') for n in range(150)])
        response=self.client.get('/customers/');column=next(c for c in response.context['columns'] if c['key']=='name')
        self.assertTrue(column['remote']);self.assertLessEqual(len(column['options']),100)
        response=self.client.get('/customers/column-choices/',{'column':'name','choice_search':'0149'})
        self.assertEqual(response.json()['values'],['Заказчик 0149'])

    def test_unfinished_tasks_go_to_latest_contract_by_date_not_new_id(self):
        raw=fixture();raw['format']='aborigen-legacy-history-v2'
        raw['tables']['LIST_DOCUMENTS'].extend([
            {'ID_DOC':99,'ID_COMPANY':2,'ID_TIP_DOC':16,'DATA_DOC':'2019-01-01','SUMMA':0},
            {'ID_DOC':12,'ID_COMPANY':2,'ID_TIP_DOC':16,'DATA_DOC':'2021-01-01','SUMMA':0}])
        run,_=apply_history(load_history(package(raw)))
        task=m.Task.objects.get(done=False)
        record=run.records.get(table='LIST_DOCUMENTS',source_id=12)
        self.assertEqual(task.contract_id,record.target_id)
        self.assertIsNone(m.Task.objects.get(done=True).contract_id)

    def test_large_tourist_choices_are_bounded_without_limiting_validation(self):
        self.login()
        m.Tourist.objects.bulk_create([m.Tourist(name=f'Справочник {n:04d}') for n in range(150)])
        selected=m.Tourist.objects.order_by('-pk').first();selected.is_default=True;selected.save()
        from .card_forms import LineCardForm
        form=LineCardForm()
        self.assertEqual(form.initial['tourist'],selected.pk)
        self.assertEqual(len(list(form.fields['tourist'].widget.choices)),2)
        form=LineCardForm(data={'tourist':str(selected.pk),'description':'Строка','amount':'10,00'})
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.cleaned_data['tourist'].pk,selected.pk)
        choices=self.client.get('/tourists/search/',{'q':'0149'}).json()['choices']
        self.assertEqual(choices[0]['id'],selected.pk)

    def test_names_only_tourists_not_merged_without_identity_evidence(self):
        raw=fixture();row=raw['tables']['LIST_TOVAR_DOC'][0]
        row.pop('ADD_NOMER_1');row.pop('ADD_DATE_ROZDENIYA')
        raw['tables']['LIST_TOVAR_DOC'].append({**row,'ID_TOVAR_DOC':31})
        apply_history(load_history(package(raw)))
        self.assertEqual(m.Tourist.objects.count(),2)

    def test_dead_background_worker_not_reported_as_running(self):
        from .legacy_history_jobs import process_alive
        self.assertFalse(process_alive(None,'job'))
        with patch('crm.legacy_history_jobs.os.kill',return_value=None),patch('pathlib.Path.exists',return_value=True),patch('pathlib.Path.read_text',return_value='123 (python) Z 1 2 3'):
            self.assertFalse(process_alive(123,'job'))
        with patch('crm.legacy_history_jobs.os.kill',side_effect=ProcessLookupError):
            self.assertFalse(process_alive(123,'job'))
