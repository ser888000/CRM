from datetime import date
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from io import BytesIO
from .models import Operator, Customer, Contract, Task
from .one_c_export import build_plan, package_bytes


class OperatorINNAndTabsTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('tabs-owner',password='test')
        self.client.force_login(self.user)
        self.operator=Operator.objects.create(name='Тест ТО',inn='0000000000')
        self.customer=Customer.objects.create(name='Тестовый заказчик')
        self.contract=Contract.objects.create(number='TEST',customer=self.customer,operator=self.operator,date=date(2026,1,1))

    def test_inn_form_validation_and_reference_editor(self):
        for value in ('123', '123456789A', '1234567890123'):
            self.operator.inn=value
            with self.assertRaises(ValidationError):self.operator.full_clean()
        for value in ('', '0000000000', '000000000000'):
            self.operator.inn=value; self.operator.full_clean()
        response=self.client.get(f'/references/operator/{self.operator.pk}/')
        self.assertContains(response,'name="reference-inn"')

    def test_inn_in_xml_and_json_including_leading_zeroes(self):
        plan=build_plan([self.contract.pk],2026)
        self.assertEqual(plan['contracts'][0]['operator']['inn'],'0000000000')
        with ZipFile(BytesIO(package_bytes(plan))) as package:
            xml=ET.fromstring(package.read('exchange.xml'))
        self.assertEqual(xml.find('CONTRACT/OPERATOR').get('INN'),'0000000000')

    def test_customer_tabs_and_pagination_keep_active_tab(self):
        for i in range(101):Task.objects.create(customer=self.customer,title=f'Задача {i}',due=date(2026,1,1))
        response=self.client.get(reverse('customer_editor',args=[self.customer.pk]),{'tab':'tasks'})
        for tab in ('overview','contracts','tasks','finance','similar'):
            self.assertContains(response,f'data-tab="{tab}"')
            self.assertContains(response,f'data-panel="{tab}"')
        self.assertIn('tab=tasks',response.context['task_links'][0]['url'])
        self.assertContains(response,'Похожих записей не найдено.')

    def test_contract_tasks_planned_first_then_earliest_date(self):
        late=Task.objects.create(contract=self.contract,title='Поздняя',due=date(2026,12,1))
        done=Task.objects.create(contract=self.contract,title='Выполненная',due=date(2026,1,1),done=True)
        early=Task.objects.create(contract=self.contract,title='Ранняя',due=date(2026,2,1))
        response=self.client.get(reverse('contract_card',args=[self.contract.pk]),{'tab':'tasks'})
        self.assertEqual([t.pk for t in response.context['tasks']],[early.pk,late.pk,done.pk])
