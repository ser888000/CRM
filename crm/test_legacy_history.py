import io
import json
import tempfile
import zipfile
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase,Client,override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from . import models as m
from .legacy_history import KEYS,load_history,prepare_history,apply_history,HistoryImportError


def fixture():
    tables={key:[] for key in KEYS}
    tables.update(COMPANY=[{'ID_COMPANY':1,'YUR_FIZ':2,'FAM_FIZ':'Примеров','NAME_FIZ':'Иван','COMPANY_NAME':'Примеров Иван','TRASH':0},{'ID_COMPANY':2,'YUR_FIZ':2,'COMPANY_NAME':'Примеров Иван','TRASH':1}], LIST_DOCUMENTS=[{'ID_DOC':10,'ID_COMPANY':1,'ID_TIP_DOC':16,'NUMBER_DOC':'A-10','DATA_DOC':'2020-01-01T12:00:00','SUMMA':500,'ADD_SUM_OPLATY_TO':200,'ID_LIST_REQUIS_FIZ':20},{'ID_DOC':11,'ID_COMPANY':2,'ID_TIP_DOC':16,'DATA_DOC':'2020-01-02','SUMMA':0}], LIST_TOVAR_DOC=[{'ID_TOVAR_DOC':30,'ID_DOC':10,'TOVAR_DOC':'Турист в договоре','SUMMA':400,'ADD_LAST_NAME':'EXAMPLE','ADD_FIRST_NAME':'IVAN','ADD_NOMER_1':'0000000000','ADD_DATE_ROZDENIYA':'1990-01-01'}], LIST_MANYS=[{'ID_MANY':k,'ID_COMPANY':1,'ID_DOC':doc,'SUM_RUB':amount,'DATE_MANY':'2020-01-01','ID_SUB_PRIZNAK_MANY':1,'ID_PRIZNAK_MANY':2,'ID_NAPR':1,'ID_LIST_SPR_LIST_SCHETS_MONY':35} for k,doc,amount in [(40,10,300),(41,10,-50),(42,10,0),(43,999,25)]], LIST_CONTACT_COMPANY=[{'ID_CONTACT':key,'ID_COMPANY':2,'ID_VID_CONTACT':1,'DATA_CONTACT':'2020-01-01T10:30:00','ID_PRIZNAK_CONTACT':status,'ID_MANAGER':1,'PRIMECHANIE':'Описание','REZULTAT_CONTACT':'Результат'} for key,status in [(50,1),(51,2)]],LIST_REQUIS_FIZ=[{'ID_LIST_REQUIS_FIZ':20,'ID_COMPANY':1,'FIO_REQUIS_FIZ':'Историческое имя','PASPORT_NUMBER':'00 00 000000'}],TIP_DOCUMENTS=[{'ID_TIP_DOCUMENT':16,'TIP_DOCUMENT':'Договор ФЛ'}],VID_CONTACT=[{'ID_VID_CONTACT':1,'DISCRIPTION_VID_CONTCT':'Звонок'}],LIST_SPR_SCHETS_MONY=[{'ID_LIST_SPR_LIST_SCHETS_MONY':35,'NAME_SCHET':'Наличные'}],MANAGERS=[{'ID_MANAGER':1,'MANAGER_NAME':'Исторический сотрудник'}])
    return {'format':'aborigen-legacy-history-v1','source_key':'synthetic:test','snapshot':'2026-10-25','tables':tables}


def package(data=None):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:archive.writestr('history.json',json.dumps(data or fixture(),ensure_ascii=False))
    stream.seek(0);return stream


class HistoryTests(TestCase):
    def test_import_links_sums_snapshots_and_no_tourist_catalog(self):
        data=load_history(package());_,_,preview=prepare_history(data)
        self.assertEqual(m.Customer.objects.count(),0)
        run,created=apply_history(data)
        self.assertTrue(created);self.assertEqual(run.summary['totals'],preview['totals'])
        contract=m.Contract.objects.get(number='A-10')
        self.assertEqual(contract.amount,Decimal('500'));self.assertEqual(contract.lines.get().amount,Decimal('400'))
        self.assertEqual(contract.cost,Decimal('200'));self.assertEqual(contract.paid,Decimal('250'))
        self.assertEqual(contract.debt,Decimal('250'));self.assertEqual(contract.profit,Decimal('300'))
        self.assertIsNone(contract.tourvisor_id)
        self.assertEqual(contract.lines.get().tourist_snapshot['Номер паспорта'],'0000000000')
        self.assertEqual(contract.legacy_customer_snapshot['person']['FIO_REQUIS_FIZ'],'Историческое имя')
        self.assertEqual(m.Tourist.objects.count(),1);self.assertEqual(m.Booking.objects.count(),0)
        self.assertEqual(m.Payment.objects.filter(kind='operator').count(),1)
        self.assertIsNone(contract.operator_paid)
        self.assertEqual(m.Payment.objects.get(kind='operator').date,contract.date)
        self.assertEqual(contract.opening_operator_paid,0)
        self.assertEqual(m.Payment.objects.get(kind='customer_refund').amount,50)
        self.assertEqual(m.Customer.objects.count(),2) # Equal names must not merge source IDs.
        self.assertEqual(run.summary['deferred_payments'],[43]);self.assertEqual(run.summary['zero_payments'],1)
        self.assertEqual(run.records.get(table='LIST_MANYS',source_id=43).status,'deferred')
        employee=m.Task.objects.first().employee
        self.assertFalse(employee.is_active);self.assertFalse(employee.has_usable_password())
        self.assertEqual(m.Task.objects.filter(done=True).count(),1)
        self.assertEqual(m.Task.objects.filter(contract__isnull=False).count(),1)
        self.assertFalse(m.Task.objects.filter(done=True,contract__isnull=False).exists())
        self.assertEqual(run.records.get(table='LIST_DOCUMENTS',source_id=10).payload,data['indexes']['LIST_DOCUMENTS'][10])

    def test_repeat_keeps_manual_edits_and_changed_snapshot_rejected(self):
        data=load_history(package());run,_=apply_history(data)
        customer=m.Customer.objects.first();customer.passport='Правка';customer.save()
        again,created=apply_history(load_history(package()))
        self.assertFalse(created);self.assertEqual(again.pk,run.pk)
        customer.refresh_from_db();self.assertEqual(customer.passport,'Правка')
        raw=fixture();raw['snapshot']='other'
        with self.assertRaises(HistoryImportError):apply_history(load_history(package(raw)))
        self.assertEqual(m.LegacyImportRun.objects.count(),1)

    def test_invalid_source_links_trash_credentials_and_cycles_rejected(self):
        for mutate in [lambda d:d['tables']['LIST_DOCUMENTS'][0].update(ID_COMPANY=999),lambda d:d['tables']['LIST_DOCUMENTS'][0].update(ID_TIP_DOC=24),lambda d:d['tables']['MANAGERS'][0].update(PASWORD='do-not-transfer'),lambda d:d['tables']['LIST_DOCUMENTS'].append(d['tables']['LIST_DOCUMENTS'][0].copy())]:
            raw=fixture();mutate(raw)
            with self.assertRaises(HistoryImportError):load_history(package(raw))
        self.assertEqual(m.Customer.objects.count(),0)

    def test_failure_rolls_back_every_section(self):
        with patch.object(m.Payment.objects,'bulk_create',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):apply_history(load_history(package()))
        self.assertEqual(m.Customer.objects.count(),0);self.assertEqual(m.Contract.objects.count(),0)
        self.assertEqual(m.Operator.objects.count(),0);self.assertEqual(m.LegacyImportRun.objects.count(),0)

    def test_finance_journal_and_contract_card_use_migrated_totals(self):
        run,_=apply_history(load_history(package()))
        user=get_user_model().objects.create_user('admin-test',is_superuser=True,is_staff=True)
        self.client.force_login(user)
        response=self.client.get(reverse('contracts'),{'start':'2020-01-01','end':'2020-01-31'})
        self.assertEqual(response.context['totals']['amount'],500);self.assertEqual(response.context['totals']['cost'],200)
        contract=m.Contract.objects.get(number='A-10')
        self.assertContains(self.client.get(reverse('contract_card',args=[contract.pk])),'Расхождение с суммой исходных строк')
        self.assertContains(self.client.get(reverse('contract_card',args=[contract.pk])),'0000000000')
        source=run.records.get(table='LIST_DOCUMENTS',source_id=10)
        self.assertEqual(self.client.get(reverse('legacy_source',args=[source.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('legacy_history_report',args=[run.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('tasks'),{'employee':m.Task.objects.first().employee_id}).status_code,200)
        clone=__import__('crm.services',fromlist=['copy_contract']).copy_contract(contract)
        self.assertEqual(clone.cost,0)

    def test_import_permissions_and_csrf(self):
        with tempfile.TemporaryDirectory() as folder,override_settings(CRM_LEGACY_IMPORT_DIR=folder):
            user=get_user_model().objects.create_user('ordinary',is_staff=True)
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('legacy_history')).status_code,403)
            self.assertEqual(self.client.get(reverse('legacy_history_status')).status_code,403)
            user.is_superuser=True;user.save()
            self.assertContains(self.client.get(reverse('legacy_history')),'Тренировочная загрузка истории')
            csrf_client=Client(enforce_csrf_checks=True);csrf_client.force_login(user)
            self.assertEqual(csrf_client.post(reverse('legacy_history'),{}).status_code,403)

    def test_amount_rounds_sqlite_cancellation_to_kopecks(self):
        apply_history(load_history(package()))
        contract=m.Contract.objects.get(number='A-10')
        contract.lines.all().delete();contract.legacy_amount_adjustment=0;contract.save()
        for value in ('12345678.91','0.02','-12345678.90'):
            m.ContractLine.objects.create(contract=contract,description='Синтетическая строка',amount=Decimal(value))
        self.assertEqual(contract.amount,Decimal('0.03'))

    def test_actual_legacy_payer_not_replaced_by_contract_customer(self):
        raw=fixture();raw['tables']['COMPANY'][1]['COMPANY_NAME']='Другой плательщик'
        raw['tables']['LIST_MANYS'][0]['ID_COMPANY']=2
        run,_=apply_history(load_history(package(raw)))
        payment=m.Payment.objects.get(kind='customer')
        self.assertEqual(payment.payer.name,'Другой плательщик')
        self.assertNotEqual(payment.legacy_payer_id,payment.contract.customer_id)
        self.assertEqual(run.summary['issue_counts']['payment_customer_differs'],1)
