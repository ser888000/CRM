import io
import subprocess
from unittest.mock import patch
from django.test import TestCase,SimpleTestCase
from django.contrib.auth import get_user_model
from django.db import IntegrityError,transaction
from .models import Customer,Operator,Contract,Country,DepartureCity,Currency,Meal,Transfer,Insurance,FuelSurcharge,ContractType,PaymentMethod,Tourist
from .card_forms import CardContractForm,CustomerCardForm,CardPaymentForm,LineCardForm
from .passport_parser import parse_passport

class DefaultTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
    def test_one_default_per_reference_and_clear(self):
        for model in [Meal,Transfer,Insurance,FuelSurcharge,ContractType,PaymentMethod,Operator,Customer,Tourist]:
            with self.subTest(model=model.__name__):
                a=model.objects.create(name='Первый',is_default=True);b=model(name='Второй',is_default=True)
                b.full_clean();b.save();a.refresh_from_db()
                self.assertFalse(a.is_default);self.assertEqual(model.objects.filter(is_default=True).get().pk,b.pk)
                b.is_default=False;b.save();self.assertFalse(model.objects.filter(is_default=True).exists())
        model=Meal
        a=model.objects.first();a.is_default=True;a.save()
        with self.assertRaises(IntegrityError),transaction.atomic():model.objects.exclude(pk=a.pk).update(is_default=True)
    def test_defaults_only_new_unbound_forms(self):
        country=Country.objects.first();country.is_default=True;country.save()
        city=DepartureCity.objects.first();city.is_default=True;city.save()
        meal=Meal.objects.create(name='Новое питание',is_default=True)
        payment=PaymentMethod.objects.create(name='Оплата по умолчанию',is_default=True)
        kind=ContractType.objects.create(name='Тип по умолчанию',is_default=True)
        operator=Operator.objects.create(name='Основной ТО',is_default=True)
        customer=Customer.objects.create(name='Основной заказчик',is_default=True)
        currency=Currency.objects.get(code='USD');currency.is_default=True;currency.save()
        form=CardContractForm()
        for name,value in [('country',country.name),('departure',city.name),('meal',meal.name),('payment_method',payment.pk),('contract_type',kind.pk),('operator',operator.pk),('customer',customer.pk),('source_currency','USD')]:
            self.assertEqual(form[name].value(),value)
        self.assertEqual(CardPaymentForm()['currency'].value(),'USD');self.assertEqual(CardPaymentForm()['method'].value(),payment.pk)
        c=Contract.objects.create(customer=customer,operator=operator,meal='Старое питание',country='Другая страна',source_currency='RUB')
        self.assertEqual(CardContractForm(instance=c)['meal'].value(),'Старое питание')
        self.assertEqual(CardContractForm(data={'meal':''})['meal'].value(),'')
        self.assertEqual(CardContractForm(initial={'meal':'Введено вручную'})['meal'].value(),'Введено вручную')
        self.assertEqual(CardPaymentForm(initial={'currency':'EUR'})['currency'].value(),'EUR')
    def test_admin_defaults_column_can_be_saved(self):
        a=Meal.objects.create(name='А',is_default=True);b=Meal.objects.create(name='Б')
        response=self.client.get('/admin/crm/meal/')
        self.assertContains(response,'По умолчанию');self.assertContains(response,'form-0-is_default')
        # Save both flags checked: the last selected record becomes the sole default.
        records=list(response.context['cl'].result_list)
        data={'_save':'Сохранить','form-TOTAL_FORMS':str(len(records)),'form-INITIAL_FORMS':str(len(records)),'form-MIN_NUM_FORMS':'0','form-MAX_NUM_FORMS':'1000'}
        for i,r in enumerate(records):data[f'form-{i}-id']=r.pk;data[f'form-{i}-is_default']='on' if r.pk in (a.pk,b.pk) else ''
        response=self.client.post('/admin/crm/meal/',data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(Meal.objects.filter(is_default=True).count(),1)

class CustomerCreationTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123');self.client.force_login(self.user)
    def test_company_and_person_create_in_dialog(self):
        r=self.client.get('/contracts/new/')
        self.assertContains(r,'data-reference-add="/references/customer/"');self.assertContains(r,'crm/reference_dialog.js');self.assertContains(self.client.get('/references/customer/new/'),'Юридическое лицо')
        data={'customer-new-kind':'company','customer-new-company_name':'ООО Пример','customer-new-inn':'7700000000','customer-new-kpp':'770001001','customer-new-ogrn':'1234567890123','customer-new-bik':'123456789','customer-new-account':'12345678901234567890','customer-new-representative':'Директор'}
        r=self.client.post('/customers/new/',data);self.assertEqual(r.status_code,200)
        customer=Customer.objects.get(pk=r.json()['id']);self.assertEqual(customer.name,'ООО Пример');self.assertEqual(customer.inn,'7700000000')
        person=self.client.post('/customers/new/',{'customer-new-kind':'person','customer-new-surname':'Иванов','customer-new-given_name':'Иван','customer-new-passport_type':'1'})
        self.assertEqual(person.status_code,200);self.assertEqual(person.json()['name'],'Иванов Иван')
        self.assertEqual(Contract.objects.count(),0)
    def test_bad_company_and_permissions(self):
        r=self.client.post('/customers/new/',{'customer-new-kind':'company','customer-new-company_name':'ООО Пример','customer-new-inn':'123'})
        self.assertEqual(r.status_code,400);self.assertIn('inn',r.json()['errors'])
        r=self.client.post('/customers/new/',{'customer-new-kind':'company'})
        self.assertIn('company_name',r.json()['errors']);self.assertFalse(Customer.objects.exists())
        user=get_user_model().objects.create_user('viewer');self.client.force_login(user)
        self.assertEqual(self.client.post('/customers/new/',{}).status_code,403)
    def test_company_is_not_matched_to_person_on_shared_contacts(self):
        from .customer_matching import customer_matches
        Customer.objects.create(kind='company',company_name='ООО Пример',main_phone='79991234567')
        match,similar=customer_matches({'name':'Иванов Иван','main_phone':'79991234567'})
        self.assertIsNone(match);self.assertFalse(similar)

class PassportEnhancementTests(SimpleTestCase):
    def test_foreign_passport_for_customer_and_short_fillers(self):
        text='P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10'
        result=parse_passport(text,'customer')
        self.assertEqual(result['name'],'ERIKSSON ANNA MARIA');self.assertEqual(result['passport_number'],'L898902C3');self.assertEqual(result['passport_type'],'0')
        self.assertNotIn('expires',result)
    def test_bilingual_labels_dates_with_spaces(self):
        result=parse_passport('Фамилия / Surname\nИВАНОВ\nИмя / Given names\nИВАН\nДата рождения / Date of birth 01 . 02 . 1990\n12 34 567890','customer')
        self.assertEqual(result['name'],'Иванов Иван');self.assertEqual(result['birthday'],'1990-02-01')
    def test_multistage_ocr_and_language_detection(self):
        from PIL import Image
        from .passport_ocr import recognize_image,OCRLanguageError
        import tempfile
        image=Image.new('RGB',(800,1000),'white')
        text='P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10'
        with tempfile.TemporaryDirectory() as folder,patch('crm.passport_ocr.subprocess.run',side_effect=[subprocess.CompletedProcess([],0,stdout='',stderr=''),subprocess.CompletedProcess([],0,stdout=text,stderr='')]) as run:
            fields,recognized=recognize_image(image,'tourist',folder)
            self.assertEqual(run.call_count,2);self.assertEqual(fields['surname'],'ERIKSSON');self.assertEqual(recognized,text)
        with tempfile.TemporaryDirectory() as folder,patch('crm.passport_ocr.subprocess.run',return_value=subprocess.CompletedProcess([],0,stdout='',stderr="Failed loading language 'rus'")):
            with self.assertRaises(OCRLanguageError):recognize_image(image,'customer',folder)
