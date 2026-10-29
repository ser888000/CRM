import base64
import copy
import hashlib
import json
from datetime import date,timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,Client
from django.urls import reverse
from django.utils import timezone
from .models import Customer,Operator,Contract,ContractLine,Tourist,ETAApplication,ETAExport,AuditEvent
from . import eta


class ETAExchangeTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('eta-owner',password='test')
        self.client.force_login(self.user)
        self.customer=Customer.objects.create(name='TEST PAYER',address='1 Example Street, Test City, Test Region, Test Country',main_phone='+70000000001')
        self.operator=Operator.objects.create(name='TEST OPERATOR')
        self.arrival=timezone.localdate()+timedelta(days=40);self.departure=self.arrival+timedelta(days=7)
        self.contract=Contract.objects.create(customer=self.customer,operator=self.operator,number='ETA-TEST',country='Шри-Ланка',hotel='TEST HOTEL',
            start=self.arrival-timedelta(days=1),end=self.departure,
            source_data={'transport':[{'terminalcodefrom':'SVO','terminalcodeto':'CMB','number':'TE100','aircompany':'TEST AIR',
                'datefrom':(self.arrival-timedelta(days=1)).isoformat(),'dateto':self.arrival.isoformat()},
                {'terminalcodefrom':'CMB','terminalcodeto':'SVO','datefrom':self.departure.isoformat()}]})
        self.tourist=self.make_tourist('EXAMPLE','1985-01-01','TEST000001')
        self.app=self.make_app(self.tourist)
        self.url=reverse('eta_page',args=[self.contract.pk])

    def make_tourist(self,surname,birthday,number):
        tourist=Tourist.objects.create(name=surname,surname=surname,given_name='TEST',gender='male',birthday=date.fromisoformat(birthday),
            nationality='Test Country',birthcountry='Test Country',passport_type='0',passport_number=number,issued=date(2020,1,1),expires=date(2040,1,1))
        ContractLine.objects.create(contract=self.contract,tourist=tourist,amount=100)
        return tourist

    def make_app(self,tourist):
        data=eta.initial_data(self.contract,tourist)
        data.update(home_city='Test City',home_region='Test Region',home_country='Test Country',hotel_address='',
            previous_visas='None, confirmed by test applicant',previous_visas_confirmed=True,travel_history_confirmed=True,
            travel_confirmed=True,identity_confirmed=True,portal_rules_checked=True,
            expected_fee=None,expected_fee_currency='',parent_tourist=None,relationship='',
            confirmed_by=self.user.pk,confirmed_at=timezone.now().isoformat(),
            answers=[{'question':'Covid Vaccination Status','answer':'Yes','confirmed':True}])
        app=ETAApplication.objects.create(contract=self.contract,tourist=tourist,preparation=data,status='ready',source_hash=eta.source_hash(self.contract,tourist))
        return app

    def export(self,apps=None):return eta.export_applications(self.contract,[a.pk for a in (apps or [self.app])],self.user)

    def result(self,batch,stage='awaiting_confirmation',app=None):
        app=app or self.app
        entry=next(a for a in batch.payload['applicants'] if a['application_id']==str(app.pk))
        summary={k:copy.deepcopy(entry['data'][k]) for k in eta.SUMMARY_GROUPS}
        summary['accommodation']['full_address']='1 Example Hotel Road, Colombo, Sri Lanka'
        summary['additional_fields']={}
        return {'schema':eta.RESULT_SCHEMA,'batch_id':str(batch.pk),'contract_id':self.contract.pk,'contract_exchange_id':str(self.contract.exchange_id),
            'handoff_token':batch.payload['handoff_token'],'results':[{'application_id':str(app.pk),'tourist_id':app.tourist_id,
                'data_sha256':entry['data_sha256'],'stage':stage,'updated_at':timezone.now().isoformat(),
                'portal_status':'Draft','application_number':'','fee':{'amount':'0.00','currency':'USD'},
                'portal_summary':summary,'hotel_address_source':'https://hotel.example.invalid/address','unconfirmed_fields':[],
                'captcha_required':False,'portal_rules_changed':False,'portal_conditions':{'text':'Fictional portal terms for automated tests only','sha256':hashlib.sha256(b'Fictional portal terms for automated tests only').hexdigest()}}]}

    def authorize(self,batch):
        payload=self.result(batch);eta.import_results(self.contract,payload,self.user);self.app.refresh_from_db()
        response=self.client.post(reverse('eta_authorize',args=[self.contract.pk,self.app.pk]),{
            'version':str(self.app.updated_at),'summary_reviewed':'on','address_reviewed':'on','conditions_confirmed':'on','fee':'0.00','currency':'USD'})
        self.assertEqual(response.status_code,302)
        self.app.refresh_from_db();self.assertIsNotNone(self.app.submission_authorized_at)
        return eta.authorization_payload(self.app)['authorization_token']

    def test_source_arrival_uses_landing_not_departure_and_payer_contacts(self):
        data=eta.initial_data(self.contract,self.tourist)
        self.assertEqual(data['arrival_date'],self.arrival.isoformat())
        self.assertNotEqual(data['arrival_date'],self.contract.start.isoformat())
        self.assertEqual(data['phone'],self.customer.main_phone);self.assertEqual(data['home_address'],self.customer.address)
        self.assertEqual(data['travel_last_14_days'],'Россия')
        self.assertNotIn('travel_history_confirmed',data)
        self.assertFalse(eta.assess(self.app))
        self.contract.source_data['transport'].append(copy.deepcopy(self.contract.source_data['transport'][0]))
        self.assertNotIn('arrival_date',eta.initial_data(self.contract,self.tourist))

    def test_export_many_single_json_deduplicates_and_email_constant(self):
        second=self.make_app(self.make_tourist('SECOND','1987-01-01','TEST000002'))
        batch=self.export([self.app,second]);self.assertEqual(len(batch.payload['applicants']),2)
        self.assertFalse(batch.payload['submission_authorized'])
        for row in batch.payload['applicants']:
            self.assertEqual(row['data']['contact']['email'],eta.EMAIL)
            self.assertEqual(row['data']['contact']['email_confirmation'],eta.EMAIL)
            self.assertEqual(row['data']['person']['occupation'],'MANAGER')
        self.assertEqual(self.export([second,self.app]).pk,batch.pk)
        self.assertEqual(ETAExport.objects.count(),1)
        self.assertEqual(ETAApplication.objects.count(),2)
        with self.assertRaises(ValidationError):self.export([self.app])

    def test_missing_and_unconfirmed_fields_block_export(self):
        self.app.preparation['answers'][0]['confirmed']=False;self.app.save()
        with self.assertRaises(ValidationError):self.export()
        self.assertFalse(ETAExport.objects.exists())
        self.assertTrue(eta.assess(self.app))

    def test_source_change_blocks_export(self):
        self.tourist.passport_number='TEST-CHANGED';self.tourist.save()
        with self.assertRaises(ValidationError):self.export()
        self.assertFalse(ETAExport.objects.exists())

    def test_child_own_passport_is_separate_despite_parent_link(self):
        child=self.make_app(self.make_tourist('CHILD',(self.arrival.replace(year=self.arrival.year-10)).isoformat(),'TESTCHILD1'))
        child.preparation.update(parent_tourist=self.tourist.pk,relationship='Parent and child');child.save()
        self.assertFalse(eta.assess(child))
        batch=self.export([self.app,child]);data=batch.payload['applicants'][1]['data']
        self.assertTrue(data['passport']['own']);self.assertEqual(data['child']['application_mode'],'separate')
        self.assertEqual(data['person']['occupation'],'')

    def test_parent_passport_mode_is_not_exportable_in_this_stage(self):
        self.app.preparation['own_passport']='no';self.app.save()
        with self.assertRaises(ValidationError):self.export()

    def test_import_matching_and_repeated_results_are_idempotent(self):
        batch=self.export();payload=self.result(batch)
        self.assertEqual(eta.import_results(self.contract,payload,self.user),1)
        self.assertEqual(eta.import_results(self.contract,payload,self.user),0)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'awaiting_confirmation')
        self.assertFalse(eta.review_issues(self.app))

    def test_wrong_tourist_hash_token_and_contract_rejected_atomically(self):
        batch=self.export();original=self.result(batch)
        variants=[]
        for key,value in [('tourist_id',999999),('data_sha256','wrong')]:
            payload=copy.deepcopy(original);payload['results'][0][key]=value;variants.append(payload)
        payload=copy.deepcopy(original);payload['handoff_token']='wrong';variants.append(payload)
        payload=copy.deepcopy(original);payload['contract_id']=99999;variants.append(payload)
        for payload in variants:
            with self.assertRaises(ValidationError):eta.import_results(self.contract,payload,self.user)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'ready')

    def test_submission_requires_user_authorization_and_same_fee(self):
        batch=self.export();payload=self.result(batch,'submitted');payload['results'][0]['application_number']='TEST-ETA'
        with self.assertRaises(ValidationError):eta.import_results(self.contract,payload,self.user)
        token=self.authorize(batch)
        payload=self.result(batch,'submitted');payload['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Acknowledgement')
        self.assertEqual(eta.import_results(self.contract,payload,self.user),1)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'submitted');self.assertIsNone(self.app.approval_notice)
        payload=self.result(batch,'under_review');payload['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Pending',fee={'amount':'5.00','currency':'USD'})
        with self.assertRaises(ValidationError):eta.import_results(self.contract,payload,self.user)

    def test_hidden_covid_yes_requires_confirmed_answer_and_fee_unknown_blocks(self):
        self.app.preparation['answers']=[{'question':'Other declaration','answer':'No','confirmed':True}];self.app.save()
        batch=self.export();payload=self.result(batch)
        payload['results'][0]['portal_summary']['additional_fields']={'Covid Vaccination Status':'Yes'}
        eta.import_results(self.contract,payload,self.user);self.app.refresh_from_db()
        self.assertTrue(eta.review_issues(self.app))
        url=reverse('eta_authorize',args=[self.contract.pk,self.app.pk])
        self.client.post(url,{'version':str(self.app.updated_at),'summary_reviewed':'on','address_reviewed':'on','conditions_confirmed':'on','fee':'0.00','currency':'USD'})
        self.app.refresh_from_db();self.assertIsNone(self.app.submission_authorized_at)

    def test_approval_notice_download_is_separate_from_acknowledgement(self):
        batch=self.export();token=self.authorize(batch)
        submitted=self.result(batch,'submitted');submitted['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Acknowledgement')
        eta.import_results(self.contract,submitted,self.user)
        approved=self.result(batch,'approved');approved['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Approved')
        with self.assertRaises(ValidationError):eta.import_results(self.contract,approved,self.user)
        pdf=b'%PDF-1.4\n% synthetic fixture\n%%EOF'
        approved['results'][0].update(approval_confirmed=True,approval_notice={'application_id':str(self.app.pk),'tourist_id':self.tourist.pk,'application_number':'TEST-ETA','mime_type':'application/pdf','content_base64':base64.b64encode(pdf).decode(),'sha256':hashlib.sha256(pdf).hexdigest()})
        self.assertEqual(eta.import_results(self.contract,approved,self.user),1)
        self.app.refresh_from_db();self.assertEqual(bytes(self.app.approval_notice),pdf)
        response=self.client.get(reverse('eta_approval',args=[self.contract.pk,self.app.pk]))
        self.assertEqual(response['Content-Type'],'application/pdf');self.assertIn('attachment',response['Content-Disposition'])
        self.assertEqual(b''.join(response.streaming_content),pdf)
        self.assertEqual(eta.import_results(self.contract,approved,self.user),0)

    def test_stale_and_invalid_pdf_result_leave_all_unchanged(self):
        batch=self.export();payload=self.result(batch);payload['results'].append(copy.deepcopy(payload['results'][0]))
        with self.assertRaises(ValidationError):eta.import_results(self.contract,payload,self.user)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'ready')
        payload=self.result(batch);eta.import_results(self.contract,payload,self.user)
        older=self.result(batch);older['results'][0]['updated_at']=(timezone.now()-timedelta(days=1)).isoformat()
        with self.assertRaises(ValidationError):eta.import_results(self.contract,older,self.user)
        with self.assertRaises(ValidationError):eta.validate_pdf({'mime_type':'text/html','content_base64':'','sha256':''})

    def test_permissions_get_safety_csrf_and_result_upload(self):
        before=(ETAApplication.objects.count(),ETAExport.objects.count(),AuditEvent.objects.count())
        response=self.client.get(self.url);self.assertEqual(response.status_code,200)
        response=self.client.get(reverse('eta_prepare',args=[self.contract.pk,self.app.pk]));self.assertEqual(response.status_code,200)
        self.assertContains(response,self.customer.main_phone);self.assertContains(response,'Россия')
        self.assertEqual(before,(ETAApplication.objects.count(),ETAExport.objects.count(),AuditEvent.objects.count()))
        strict=Client(enforce_csrf_checks=True);strict.force_login(self.user)
        self.assertEqual(strict.post(self.url,{'tourists':[self.tourist.pk]}).status_code,403)
        batch=self.export();payload=self.result(batch)
        file=SimpleUploadedFile('result.json',json.dumps(payload).encode(),content_type='application/json')
        response=self.client.post(reverse('eta_result_import',args=[self.contract.pk]),{'result_file':file,'checked':'on'})
        self.assertEqual(response.status_code,302);self.app.refresh_from_db();self.assertEqual(self.app.status,'awaiting_confirmation')
        self.assertEqual(self.client.get(reverse('eta_export',args=[self.contract.pk])).status_code,405)
        user=get_user_model().objects.create_user('eta-readonly')
        user.user_permissions.add(*Permission.objects.filter(codename__in=[p.split('.')[1] for p in eta.READ_PERMS]))
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertEqual(self.client.post(reverse('eta_export',args=[self.contract.pk]),{'applications':[str(self.app.pk)]}).status_code,403)
        self.assertEqual(self.client.get(reverse('eta_export_download',args=[self.contract.pk,batch.pk])).status_code,403)

    def test_select_does_not_create_duplicates_or_take_foreign_tourists(self):
        self.client.post(self.url,{'tourists':[self.tourist.pk]})
        self.assertEqual(ETAApplication.objects.count(),1)
        foreign=Tourist.objects.create(name='NOT LINKED')
        response=self.client.post(self.url,{'tourists':[foreign.pk]})
        self.assertEqual(response.status_code,200);self.assertEqual(ETAApplication.objects.count(),1)

    def test_return_requires_portal_check_and_revokes_previous_export(self):
        batch=self.export();payload=self.result(batch,'error');payload['results'][0]['stop_reason']='Synthetic unknown send result; check portal first'
        eta.import_results(self.contract,payload,self.user);self.app.refresh_from_db()
        url=reverse('eta_return',args=[self.contract.pk,self.app.pk])
        self.client.post(url,{'version':str(self.app.updated_at),'reason':'Manual check'})
        self.app.refresh_from_db();self.assertEqual(self.app.active_export_id,batch.pk)
        self.client.post(url,{'version':str(self.app.updated_at),'reason':'Checked no submission','portal_checked_no_submission':'on'})
        self.app.refresh_from_db();self.assertIsNone(self.app.active_export_id)
        with self.assertRaises(ValidationError):eta.import_results(self.contract,self.result(batch),self.user)

    def test_prepare_form_saves_valid_data_and_does_not_change_tourist_or_payer(self):
        original_phone=self.customer.main_phone;original_passport=self.tourist.passport_number
        p=copy.deepcopy(self.app.preparation)
        data={key:('on' if value is True else '' if value is None or value is False else str(value)) for key,value in p.items() if key not in ('answers','confirmed_by','confirmed_at')}
        data.update(version=str(self.app.updated_at),**{'answers-TOTAL_FORMS':'1','answers-INITIAL_FORMS':'1','answers-MIN_NUM_FORMS':'0','answers-MAX_NUM_FORMS':'50',
            'answers-0-question':'Covid Vaccination Status','answers-0-answer':'Yes','answers-0-confirmed':'on'})
        response=self.client.post(reverse('eta_prepare',args=[self.contract.pk,self.app.pk]),data)
        self.assertEqual(response.status_code,302)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'ready');self.assertEqual(self.app.preparation['confirmed_by'],self.user.pk)
        self.customer.refresh_from_db();self.tourist.refresh_from_db()
        self.assertEqual(self.customer.main_phone,original_phone);self.assertEqual(self.tourist.passport_number,original_passport)
        audit=AuditEvent.objects.get(action='eta_prepared')
        self.assertNotIn(original_passport,json.dumps(audit.changes))

    def test_unexpected_fee_and_captcha_require_stop_not_authorization(self):
        self.app.preparation.update(expected_fee='0.00',expected_fee_currency='USD');self.app.save()
        batch=self.export();payload=self.result(batch);payload['results'][0]['fee']['amount']='50.00';payload['results'][0]['captcha_required']=True
        eta.import_results(self.contract,payload,self.user);self.app.refresh_from_db()
        issues=eta.review_issues(self.app)
        self.assertTrue(any('Неожиданный сбор' in issue for issue in issues))
        self.assertTrue(any('CAPTCHA' in issue for issue in issues))
        self.client.post(reverse('eta_authorize',args=[self.contract.pk,self.app.pk]),{'version':str(self.app.updated_at),'summary_reviewed':'on','address_reviewed':'on','conditions_confirmed':'on','fee':'50.00','currency':'USD'})
        self.app.refresh_from_db();self.assertIsNone(self.app.submission_authorized_at)

    def test_approval_metadata_wrong_person_or_checksum_does_not_save(self):
        batch=self.export();token=self.authorize(batch)
        payload=self.result(batch,'submitted');payload['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Acknowledgement')
        eta.import_results(self.contract,payload,self.user)
        pdf=b'%PDF-1.4\n% synthetic fixture\n%%EOF'
        approved=self.result(batch,'approved');approved['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Approved',approval_confirmed=True,
            approval_notice={'application_id':str(self.app.pk),'tourist_id':999999,'application_number':'TEST-ETA','mime_type':'application/pdf','content_base64':base64.b64encode(pdf).decode(),'sha256':hashlib.sha256(pdf).hexdigest()})
        with self.assertRaises(ValidationError):eta.import_results(self.contract,approved,self.user)
        approved['results'][0]['approval_notice']['tourist_id']=self.tourist.pk
        approved['results'][0]['approval_notice']['sha256']='wrong'
        with self.assertRaises(ValidationError):eta.import_results(self.contract,approved,self.user)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'submitted');self.assertIsNone(self.app.approval_notice)

    def test_malformed_hotel_source_blocks_confirmation_without_crashing(self):
        batch=self.export();payload=self.result(batch);payload['results'][0]['hotel_address_source']='https://['
        eta.import_results(self.contract,payload,self.user);self.app.refresh_from_db()
        self.assertTrue(eta.review_issues(self.app))
        self.assertEqual(self.client.get(reverse('eta_detail',args=[self.contract.pk,self.app.pk])).status_code,200)

    def test_payer_change_is_detected(self):
        batch=self.export()
        self.customer.address='Changed test address';self.customer.save()
        with self.assertRaises(ValidationError):eta.import_results(self.contract,self.result(batch),self.user)

    def test_referral_before_submission_is_recorded_without_inventing_application_number(self):
        batch=self.export();payload=self.result(batch,'referral')
        payload['results'][0].update(portal_status='Refer to immigration office',stop_reason='Fictional eligibility referral')
        self.assertEqual(eta.import_results(self.contract,payload,self.user),1)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'referral');self.assertEqual(self.app.application_number,'')
        self.assertIsNone(self.app.submission_authorized_at)

    def test_changed_terms_after_authorization_do_not_submit(self):
        batch=self.export();token=self.authorize(batch)
        payload=self.result(batch,'submitted')
        payload['results'][0].update(application_number='TEST-ETA',authorization_token=token,portal_status='Acknowledgement')
        payload['results'][0]['portal_conditions']['text']='Changed conditions after consent'
        with self.assertRaises(ValidationError):eta.import_results(self.contract,payload,self.user)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'awaiting_confirmation')

    def test_duplicate_passport_records_do_not_create_two_live_jobs(self):
        duplicate=self.make_app(self.make_tourist('EXAMPLE','1985-01-01','TEST000001'))
        with self.assertRaises(ValidationError):self.export([self.app,duplicate])
        self.assertEqual(ETAExport.objects.count(),0)
        self.export([self.app])
        with self.assertRaises(ValidationError):self.export([duplicate])
        self.assertEqual(ETAExport.objects.count(),1)

    def test_stale_hotel_address_is_not_borrowed_for_a_different_hotel(self):
        self.contract.source_data['hotel']=[{'name':'OTHER HOTEL','address':'Old unrelated address'}]
        initial=eta.initial_data(self.contract,self.tourist)
        self.assertEqual(initial['hotel_name'],'TEST HOTEL')
        self.assertFalse(initial.get('hotel_address'))
