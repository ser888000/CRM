from datetime import date,timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Customer,Operator,Contract,Payment,PaymentMethod

class SharedJournalPeriodTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','test@example.test','test-password');self.client.force_login(self.user)
        self.today=date(2026,10,25)
        customer=Customer.objects.create(name='Петров');operator=Operator.objects.create(name='ТО');method=PaymentMethod.objects.create(name='Карта')
        for offset in (-3650,0,1):
            day=self.today+timedelta(days=offset)
            c=Contract.objects.create(customer=customer,operator=operator,date=day,number=str(offset))
            Payment.objects.create(contract=c,date=day,amount=100,kind='customer',method=method)
    def test_first_open_defaults_today_and_blank_dates_never_mean_all(self):
        with patch('crm.journal_period.timezone.localdate',return_value=self.today):
            for path in ('/','/finances/'):
                with self.subTest(path=path):
                    for suffix in ('','?start=&end=','?period=all'):
                        response=self.client.get(path+suffix,follow=True)
                        self.assertEqual(response.context['count'],1);self.assertEqual(response.context['period'],'today')
                        self.assertEqual(response.context['start_value'],self.today.isoformat());self.assertEqual(response.context['end_value'],self.today.isoformat())
    def test_tomorrow_restore_refresh_and_reset_only_filters(self):
        with patch('crm.journal_period.timezone.localdate',return_value=self.today):
            for path in ('/','/finances/'):
                response=self.client.get(path,{'period':'tomorrow','customer':'нет','f_number':'missing'})
                self.assertEqual(response.context['count'],0)
                response=self.client.get(path,follow=True)
                self.assertEqual(response.context['period'],'tomorrow');self.assertEqual(response.context['count'],0)
                response=self.client.get(path+'?reset=1',follow=True)
                self.assertEqual(response.context['period'],'tomorrow');self.assertEqual(response.context['count'],1)
                self.assertNotIn('customer',response.wsgi_request.GET);self.assertNotIn('f_number',response.wsgi_request.GET)
                self.assertContains(response,'aria-pressed="true"')
    def test_custom_dates_single_bound_and_invalid_dates(self):
        with patch('crm.journal_period.timezone.localdate',return_value=self.today):
            for path in ('/','/finances/'):
                response=self.client.get(path,{'start':'2016-10-27','end':'2026-10-26','period':'custom'})
                self.assertEqual(response.context['count'],3)
                response=self.client.get(path,{'reset':'1','start':'2016-10-27','end':'2026-10-26','period':'custom','customer':'нет'},follow=True)
                self.assertEqual(response.context['count'],3);self.assertEqual(response.context['period'],'custom')
                response=self.client.get(path,{'start':'2026-10-26','end':'','period':'custom'})
                self.assertEqual(response.context['count'],1);self.assertEqual(response.context['end_value'],'2026-10-26')
                for data in ({'start':'bad','end':'bad'},{'start':'2026-10-26','end':'2026-10-25'}):
                    response=self.client.get(path,{**data,'period':'custom'})
                    self.assertEqual(response.context['count'],0);self.assertFalse(response.context['dateform'].is_valid())
    def test_today_is_relative_on_next_day_and_states_are_separate(self):
        with patch('crm.journal_period.timezone.localdate',return_value=self.today):
            self.client.get('/?period=today&customer=Петров')
            self.client.get('/finances/?period=tomorrow')
        with patch('crm.journal_period.timezone.localdate',return_value=self.today+timedelta(days=1)):
            response=self.client.get('/',follow=True)
            self.assertEqual(response.context['start_value'],'2026-10-26');self.assertEqual(response.context['period'],'today')
            self.assertEqual(response.wsgi_request.GET.get('customer'),'Петров')
            response=self.client.get('/finances/',follow=True)
            self.assertEqual(response.context['start_value'],'2026-10-27');self.assertEqual(response.context['period'],'tomorrow')
