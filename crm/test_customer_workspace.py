from decimal import Decimal
from django.test import TestCase,Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from .models import Customer,Operator,Contract,AuditEvent

class CustomerWorkspaceTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','test@example.test','test-password');self.client.force_login(self.user)
        self.person=Customer.objects.create(surname='Петров',given_name='Иван',main_phone='+7 (999) 111-22-33',phones='8 999 222-33-44',main_email='TEST@example.test')
        self.company=Customer.objects.create(kind='company',company_name='ООО Тест',inn='1234567890',main_phone='70000000000')
        self.operator=Operator.objects.create(name='ТО')
        self.contract=Contract.objects.create(customer=self.person,operator=self.operator,number='100')
    def test_search_unicode_phone_email_and_company(self):
        for params in ({'name':'пЕтРоВ'},{'phone':'89991112233'},{'phone':'79992223344'},{'email':'test@EXAMPLE'}):
            response=self.client.get('/customers/',params);self.assertEqual(response.context['count'],1)
            self.assertEqual(response.context['table_rows'][0]['customer'].pk,self.person.pk)
        response=self.client.get('/customers/?name=1234567890&kind=company');self.assertEqual(response.context['count'],1)
        self.assertContains(response,'Фильтр: Телефоны')
        self.assertNotContains(response,'Паспорт: серия и номер')
    def test_column_filters_sort_counts_and_preserved_session(self):
        response=self.client.get('/customers/',{'f_kind':['Физическое лицо','Юридическое лицо'],'sort':'-contracts'})
        self.assertEqual([r['customer'].pk for r in response.context['table_rows']],[self.person.pk,self.company.pk])
        self.assertEqual(response.context['table_rows'][0]['values']['contracts'],1)
        self.client.get('/tasks/')
        self.assertEqual(self.client.get('/customers/',follow=True).context['sort'],'-contracts')
        self.assertEqual(self.client.get('/customers/?reset=1',follow=True).context['count'],2)
    def data(self,**kwargs):
        values={'kind':'person','surname':'Новый','given_name':'Иван','main_phone':'79990000000','passport_type':'1'};values.update(kwargs)
        return {'customer-'+key:value for key,value in values.items()}
    def test_create_and_edit_shared_customer_preserves_context(self):
        response=self.client.post('/customers/add/',{**self.data(),'return_query':'kind=person&next=https://example.test'})
        self.assertEqual(response.status_code,302);self.assertNotIn('next=',response.url)
        new=Customer.objects.get(surname='Новый');self.assertEqual(new.name,'Новый Иван')
        response=self.client.get(f'/customers/{self.person.pk}/');self.assertContains(response,'100');self.assertEqual(response.context['contract_count'],1)
        token=response.context['form']['version'].value()
        response=self.client.post(f'/customers/{self.person.pk}/',{**self.data(surname='Петров',given_name='Пётр',version=token),'return_query':'kind=person'})
        self.assertEqual(response.status_code,302);self.person.refresh_from_db();self.assertEqual(self.person.name,'Петров Пётр')
        self.assertEqual(self.contract.customer.name,'Петров Пётр')
        self.assertEqual(AuditEvent.objects.filter(object_type='crm.Customer').count(),2)
    def test_company_validation_and_stale_edit(self):
        response=self.client.post('/customers/add/',self.data(kind='company',company_name='ООО Новое',inn='12'))
        self.assertEqual(response.status_code,200);self.assertFalse(Customer.objects.filter(company_name='ООО Новое').exists())
        response=self.client.post('/customers/add/',self.data(kind='company',company_name='ООО Новое',inn='1234567890'))
        self.assertEqual(response.status_code,302);self.assertTrue(Customer.objects.filter(name='ООО Новое',kind='company').exists())
        token=self.client.get(f'/customers/{self.person.pk}/').context['form']['version'].value()
        self.person.main_phone='70000000001';self.person.save()
        response=self.client.post(f'/customers/{self.person.pk}/',self.data(version=token))
        self.assertContains(response,'изменён в другом окне');self.person.refresh_from_db();self.assertEqual(self.person.main_phone,'70000000001')
    def test_view_only_and_csrf_and_existing_ajax_creation(self):
        viewer=get_user_model().objects.create_user('viewer');viewer.user_permissions.add(Permission.objects.get(codename='view_customer'));self.client.force_login(viewer)
        response=self.client.get('/customers/');self.assertEqual(response.status_code,200);self.assertNotContains(response,'+ Новый заказчик')
        response=self.client.get(f'/customers/{self.person.pk}/');self.assertEqual(response.status_code,200);self.assertNotContains(response,'Сохранить заказчика');self.assertEqual(response.context['contract_count'],0)
        self.assertEqual(self.client.get('/customers/add/').status_code,403)
        self.assertEqual(self.client.post(f'/customers/{self.person.pk}/',self.data()).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user)
        self.assertEqual(secure.post('/customers/add/',self.data()).status_code,403)
        self.client.force_login(self.user)
        response=self.client.post('/customers/new/',{'customer-new-kind':'person','customer-new-surname':'Из диалога','customer-new-given_name':'Иван'})
        self.assertEqual(response.status_code,200);self.assertIn('id',response.json())
    def test_continuous_list_and_similar_records_are_not_merged(self):
        similar=Customer.objects.create(name=self.person.name,main_phone=self.person.main_phone)
        response=self.client.get(f'/customers/{self.person.pk}/');self.assertContains(response,'Похожие записи');self.assertEqual(response.context['similar'][0].pk,similar.pk)
        Customer.objects.bulk_create([Customer(name='Заказчик '+str(i)) for i in range(101)])
        response=self.client.get('/customers/?page=2');self.assertEqual(response.context['count'],104);self.assertEqual(len(response.context['table_rows']),104)
        self.assertIn('page=2',response.context['return_query'])

    def test_form_scripts_resolve_to_existing_static_assets(self):
        from django.contrib.staticfiles.finders import find
        from .customer_workspace import CustomerEditor
        from .finance_views import FinanceEditor
        from .forms import TouristForm
        for form in (CustomerEditor(),FinanceEditor(),TouristForm()):
            for path in form.media._js:
                self.assertNotIn('?',path)
                self.assertTrue(find(path),path)
