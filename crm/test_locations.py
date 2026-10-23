from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import DepartureCity,Country,Customer,Operator,Contract
from .forms import ContractForm

class LocationTests(TestCase):
    def test_seeded_codes_and_details(self):
        self.assertEqual(DepartureCity.objects.count(),77)
        self.assertEqual(Country.objects.count(),70)
        abakan=DepartureCity.objects.get(code='53')
        self.assertEqual(abakan.name,'Абакан')
        self.assertEqual(abakan.details['code_avia'],'ABA')
        self.assertEqual(Country.objects.get(code='46').name,'Абхазия')
    def test_matching_preserves_code_and_handles_case_spaces(self):
        self.assertEqual(DepartureCity.match('  МОСКВА  ').name,'Москва')
        self.assertEqual(Country.match('  египет ').name,'Египет')
        self.assertIsNone(Country.match('Неизвестная страна'))
        DepartureCity.objects.create(code='test',name='Орёл')
        self.assertEqual(DepartureCity.match('ОРЕЛ').code,'test')
    def test_text_fields_support_canonical_and_unlisted_names(self):
        customer=Customer.objects.create(name='Клиент')
        operator=Operator.objects.create(name='ТО')
        data={'customer':customer.pk,'operator':operator.pk,'adults':'0','children':'0','infants':'0','source_currency':'RUB','date':'2026-10-22','departure':' москва ','country':'египет'}
        form=ContractForm(data=data)
        self.assertTrue(form.is_valid(),form.errors)
        contract=form.save()
        self.assertEqual(contract.departure,'Москва')
        self.assertEqual(contract.country,'Египет')
        data.update(departure='Новый город',country='Новая страна')
        form=ContractForm(data=data)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.save().departure,'Новый город')
        self.assertEqual(DepartureCity.objects.count(),77)
    def test_suggestions_and_safe_html(self):
        from .widgets import LocationInput
        html=LocationInput(DepartureCity).render('departure','',attrs={'id':'id_departure'})
        import json,re
        names=json.loads(re.search(r'<script[^>]*>(.*?)</script>',html).group(1))
        self.assertIn('Москва',names)
        self.assertIn('role="combobox"',html)
        self.assertIn('role="listbox"',html)
        DepartureCity.objects.create(code='test',name='</script><script>alert(1)</script>')
        html=LocationInput(DepartureCity).render('departure','',attrs={'id':'id_departure'})
        self.assertNotIn('</script><script>alert(1)</script>',html)
    def test_admin_form_renders_reference_fields_and_assets(self):
        user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123')
        self.client.force_login(user)
        response=self.client.get('/admin/crm/contract/add/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'crm/location_input.js')
        self.assertContains(response,'crm/location_input_v2.css')
        for url in ['/admin/crm/country/','/admin/crm/departurecity/']:
            self.assertEqual(self.client.get(url).status_code,200)
