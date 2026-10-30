from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase,Client
from django.urls import reverse
from . import eta,test_eta as base
from .models import ETAApplication,ETAExport,Tourist,ContractLine


class ETASimpleDownloadTests(TestCase):
    setUp=base.ETAExchangeTests.setUp
    make_tourist=base.ETAExchangeTests.make_tourist
    make_app=base.ETAExchangeTests.make_app

    def download_url(self,tourist=None):return reverse('eta_simple_download',args=[self.contract.pk,(tourist or self.tourist).pk])

    def test_exact_format_current_crm_and_arrival_instead_of_departure(self):
        # An old preparation snapshot must not override the current CRM card.
        self.app.preparation.update(surname='STALE',home_address='STALE');self.app.save()
        response=self.client.get(self.download_url());payload=response.json()
        self.assertEqual(payload,{
            'hotel':{'name':'TEST HOTEL','address':''},
            'flight':{'arrival_date':self.arrival.isoformat(),'departure_airport':'SVO','airline':'TEST AIR','flight_number':'TE100'},
            'tourists':[{'surname':'EXAMPLE','given_names':'TEST','gender':'male','birth_date':'1985-01-01',
                         'nationality':'Test Country','birth_country':'Test Country','passport_number':'TEST000001',
                         'passport_issued':'2020-01-01','passport_expires':'2040-01-01',
                         'home_address':self.customer.address,'phone':self.customer.main_phone}]})
        self.assertIn('attachment;',response['Content-Disposition']);self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertEqual(ETAApplication.objects.count(),1);self.assertEqual(ETAExport.objects.count(),0)

    def test_missing_data_downloads_without_job_or_validation(self):
        self.app.delete()
        Tourist.objects.filter(pk=self.tourist.pk).update(surname='',given_name='',birthday=None,passport_number='',issued=None,expires=None)
        self.contract.source_data={};self.contract.hotel='';self.contract.save()
        response=self.client.get(self.download_url());self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['tourists'][0]['passport_number'],'');self.assertEqual(data['tourists'][0]['birth_date'],'')
        self.assertEqual(data['flight'],dict.fromkeys(('arrival_date','departure_airport','airline','flight_number'),''))
        self.assertEqual(ETAApplication.objects.count(),0);self.assertEqual(ETAExport.objects.count(),0)
        page=self.client.get(reverse('eta_page',args=[self.contract.pk]))
        self.assertContains(page,self.download_url());self.assertContains(page,'Скачать JSON')

    def test_read_only_user_can_download_but_needs_existing_read_permissions(self):
        reader=get_user_model().objects.create_user('eta-reader')
        reader.user_permissions.set(Permission.objects.filter(content_type__app_label='crm',codename__in=[p.split('.')[1] for p in eta.READ_PERMS]))
        self.client.force_login(reader)
        self.assertEqual(self.client.get(self.download_url()).status_code,200)
        page=self.client.get(reverse('eta_page',args=[self.contract.pk]));self.assertContains(page,self.download_url())
        reader.user_permissions.clear();self.assertEqual(self.client.get(self.download_url()).status_code,403)
        self.assertEqual(Client().get(self.download_url()).status_code,302)

    def test_only_requested_linked_tourist_is_exported(self):
        other=self.make_tourist('SECOND','1990-02-01','TEST000002')
        response=self.client.get(self.download_url(other));self.assertEqual(len(response.json()['tourists']),1)
        self.assertEqual(response.json()['tourists'][0]['surname'],'SECOND')
        ContractLine.objects.filter(contract=self.contract,tourist=other).delete()
        self.assertEqual(self.client.get(self.download_url(other)).status_code,404)
