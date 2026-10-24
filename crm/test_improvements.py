import copy
import io
import subprocess
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from PIL import Image
from django.test import TestCase,SimpleTestCase,override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import Customer,Operator,Contract,ContractLine,PaymentMethod,Task,TaskTemplate,Meal
from .card_forms import CustomerCardForm,CardContractForm,CardPaymentForm
from .forms import CustomerForm
from .customer_matching import customer_matches,phone_key
from .tourvisor import apply_order,normalize_order,TourvisorError,GROUPS
from .test_tourvisor import sample
from .passport_ocr import parse_passport

class JournalImprovementTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
        self.customer=Customer.objects.create(surname='Петров',given_name='Сергей',main_phone='+7 (999) 111-22-33',main_email='TEST@example.test')
        self.operator=Operator.objects.create(name='ТО')
        self.cards=[]
        for i,country in enumerate(['Египет','Турция','Египет']):
            c=Contract.objects.create(customer=self.customer,operator=self.operator,number=str(i+1),country=country,date=date(2026,10,24),adults=2,children=i,departure='Москва',notes='Пример',operator_paid=date(2026,10,24))
            ContractLine.objects.create(contract=c,description='Тур',amount=[300,100,200][i]);self.cards.append(c)
    def test_unicode_contact_search_and_layout(self):
        for data in [{'customer':'пЕтРоВ'},{'email':'test@EXAMPLE'},{'phone':'89991112233'}]:
            with self.subTest(data=data):self.assertEqual(self.client.get('/',data).context['count'],3)
        r=self.client.get('/',follow=True)
        for label in ['Способ оплаты','Примечание','Город вылета','Дата оплаты ТО','Взр','Дети','Месяц (текущий)']:self.assertContains(r,label)
        for name in ['number','operator','country']:self.assertNotContains(r,f'name="{name}"')
        self.assertNotContains(r,'документов · Сумма')
    def test_multi_column_filters_sort_and_totals(self):
        r=self.client.get('/',{'f_country':['Египет','Турция'],'f_children':['0','2'],'sort':'amount'})
        self.assertEqual([c.pk for c in r.context['rows']],[self.cards[2].pk,self.cards[0].pk])
        self.assertEqual(r.context['count'],2);self.assertEqual(r.context['totals']['amount'],Decimal('500'))
        self.assertContains(r,'ИТОГО: 2')
        self.assertEqual(len(r.context['footer']),len(r.context['columns']))
        r=self.client.get('/',{'f_country':'Египет','sort':'-amount'})
        self.assertEqual([c.pk for c in r.context['rows']],[self.cards[0].pk,self.cards[2].pk])
    def test_quick_periods(self):
        self.cards[0].date=date(2026,9,30);self.cards[0].save()
        self.cards[1].date=date(2026,10,1);self.cards[1].save()
        with patch('crm.contract_journal.timezone.localdate',return_value=date(2026,10,24)):
            self.assertEqual(self.client.get('/',{'period':'today'}).context['count'],1)
            r=self.client.get('/',{'period':'month'})
            self.assertEqual(r.context['count'],2);self.assertEqual(r.context['start_value'],'2026-10-01');self.assertEqual(r.context['end_value'],'2026-10-31')
    def test_customer_name_generated_on_server_and_admin(self):
        form=CustomerCardForm({'surname':'Иванов','given_name':'Иван','patronymic':'Иванович','name':'Неверное ФИО'})
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(form.save().name,'Иванов Иван Иванович')
        admin=self.client.get('/admin/crm/customer/add/')
        self.assertContains(admin,'crm/customer_name.js')
        self.assertEqual([k for k in CustomerForm().fields if k in ('surname','given_name','patronymic','name')],['surname','given_name','patronymic','name'])
        self.assertEqual(CustomerCardForm().fields['phones'].widget.attrs['rows'],3)
    def test_defaults_suggestions_and_task_empty_section(self):
        self.assertEqual(CardContractForm()['source_currency'].value(),'RUB')
        self.assertEqual(CardPaymentForm()['currency'].value(),'RUB')
        Meal.objects.create(name='Тестовое питание')
        r=self.client.get(f'/contracts/{self.cards[0].pk}/')
        self.assertContains(r,__import__('json').dumps('Тестовое питание')[1:-1])
        self.assertNotContains(r,'Выберите недостающие задачи')
        self.assertContains(r,'Топливный сбор');self.assertNotContains(r,'Ссылка на тур у ТО')
        f=CardContractForm().fields['meal'];self.assertIsNone(f.widget.attrs.get('readonly'))

class MatchingTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
        self.order=sample();self.data=normalize_order(self.order)['customer']
    def test_phone_and_case_reuse_without_overwriting_manual_data(self):
        data={**self.data,'main_phone':'8 (999) 111-22-33','main_email':'PERSON@example.test','name':self.data['name'].lower()}
        self.order.update(phone='+7 999 1112233',email='person@EXAMPLE.test')
        c=Customer.objects.create(**data,phones='8 900 000-00-00',passport='Ручное значение')
        contract=apply_order(self.order,self.user,set(GROUPS))
        self.assertEqual(contract.customer_id,c.pk);self.assertEqual(Customer.objects.count(),1)
        c.refresh_from_db();self.assertEqual(c.passport,'Ручное значение');self.assertEqual(c.phones,'8 900 000-00-00')
        self.assertEqual(phone_key('8 (999) 111-22-33'),phone_key('+7 999 1112233'))
    def test_repeat_import_does_not_duplicate_reused_customer(self):
        customer=Customer.objects.create(**self.data)
        first=apply_order(self.order,self.user,set(GROUPS))
        other=copy.deepcopy(self.order);other['id']='999123'
        second=apply_order(other,self.user,set(GROUPS))
        self.assertEqual(first.customer_id,second.customer_id)
        apply_order(self.order,self.user,{'customer'},expected=first.pk)
        self.assertEqual(Customer.objects.count(),1)
        self.assertEqual(first.customer_id,customer.pk)
    def test_conflicting_contacts_require_choice_and_selected_id_is_validated(self):
        c=Customer.objects.create(**{**self.data,'main_phone':'79990000000','main_email':'different@example.test'})
        self.assertIsNone(customer_matches(self.data)[0])
        with self.assertRaises(TourvisorError):apply_order(self.order,self.user,set(GROUPS))
        self.assertEqual(Contract.objects.count(),0)
        with self.assertRaises(TourvisorError):apply_order(self.order,self.user,set(GROUPS),customer_choice='99999')
        contract=apply_order(self.order,self.user,set(GROUPS),customer_choice=str(c.pk))
        self.assertEqual(contract.customer_id,c.pk)
    def test_ambiguous_exact_matches_require_choice_or_explicit_new(self):
        Customer.objects.create(**self.data);Customer.objects.create(**self.data)
        self.assertIsNone(customer_matches(self.data)[0])
        with patch('crm.import_views.fetch_order',return_value=self.order):
            r=self.client.post('/tourvisor/import/',{'action':'lookup','order_id':self.order['id']})
        self.assertContains(r,'Проверка заказчика')
        token=self.client.session['tourvisor_preview']['token']
        data={'action':'confirm','token':token,'groups':list(GROUPS),'end':'2026-12-08'}
        r=self.client.post('/tourvisor/import/',data)
        self.assertEqual(r.status_code,200);self.assertEqual(Contract.objects.count(),0)
        data['customer_choice']='new'
        self.assertEqual(self.client.post('/tourvisor/import/',data).status_code,302)
        self.assertEqual(Customer.objects.count(),3)

class PassportParserTests(SimpleTestCase):
    def test_russian_labelled_fields(self):
        fields=parse_passport('ФАМИЛИЯ ИВАНОВ\nИМЯ ИВАН\nОТЧЕСТВО ИВАНОВИЧ\nДАТА РОЖДЕНИЯ 01.02.1990\nДАТА ВЫДАЧИ 03.04.2010\n123-456\n12 34 567890','customer')
        self.assertEqual(fields['name'],'Иванов Иван Иванович');self.assertEqual(fields['birthday'],'1990-02-01')
        self.assertEqual(fields['passport_number'],'1234567890');self.assertEqual(fields['passport_code'],'123-456')
    def test_international_mrz_checks(self):
        text='P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10'
        fields=parse_passport(text,'tourist')
        self.assertEqual(fields['surname'],'ERIKSSON');self.assertEqual(fields['passport_number'],'L898902C3')
        self.assertEqual(fields['birthday'],'1974-08-12');self.assertEqual(fields['gender'],'female')
        fields=parse_passport(text.replace('L898902C36','L898902C30'),'tourist')
        self.assertNotIn('passport_number',fields)

class PassportEndpointTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
    def image(self):
        b=io.BytesIO();Image.new('RGB',(30,30),'white').save(b,format='PNG')
        return SimpleUploadedFile('passport.png',b.getvalue(),content_type='image/png')
    def test_ocr_only_returns_preview_without_database_changes(self):
        with patch('crm.passport_ocr.shutil.which',return_value='/usr/bin/tesseract'),patch('crm.passport_ocr.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout='ФАМИЛИЯ ИВАНОВ\nИМЯ ИВАН',stderr='')) as run:
            r=self.client.post('/passport/recognize/',{'kind':'customer','passport':self.image()})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['fields']['name'],'Иванов Иван')
        self.assertFalse(Customer.objects.exists());self.assertIn('no-store',r['Cache-Control'])
        self.assertFalse(__import__('pathlib').Path(run.call_args.args[0][1]).exists())
    def test_invalid_upload_and_missing_engine(self):
        with patch('crm.passport_ocr.shutil.which',return_value='/usr/bin/tesseract'):
            r=self.client.post('/passport/recognize/',{'kind':'customer','passport':SimpleUploadedFile('file.png',b'not image')})
            self.assertEqual(r.status_code,400)
        with patch('crm.passport_ocr.shutil.which',return_value=None):
            self.assertEqual(self.client.post('/passport/recognize/',{'kind':'tourist','passport':self.image()}).status_code,503)
    def test_permissions_and_csrf(self):
        user=get_user_model().objects.create_user('viewer',password='test-password-123');self.client.force_login(user)
        self.assertEqual(self.client.post('/passport/recognize/',{'kind':'customer','passport':self.image()}).status_code,403)
        from django.test import Client
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post('/passport/recognize/',{'kind':'customer','passport':self.image()}).status_code,403)
