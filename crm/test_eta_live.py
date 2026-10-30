import copy
import hashlib
import json
from datetime import timedelta
from email.message import EmailMessage
from django.test import TestCase,Client,override_settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from . import test_eta as base_eta
from . import eta,eta_transport,eta_mail
from .models import ETAApplication,ETAOfficialNotice


@override_settings(ETA_EXECUTOR_ENABLED=True,ETA_WORKER_TOKEN='w'*48,ETA_MAIL_TOKEN='m'*48)
class ETALiveTests(TestCase):
    setUp=base_eta.ETAExchangeTests.setUp
    make_tourist=base_eta.ETAExchangeTests.make_tourist
    make_app=base_eta.ETAExchangeTests.make_app
    export=base_eta.ETAExchangeTests.export
    result=base_eta.ETAExchangeTests.result
    authorize=base_eta.ETAExchangeTests.authorize

    def queue(self):return eta_transport.enqueue(self.contract,[self.app.pk],self.user)
    def claim(self):return eta_transport.claim('worker-1')
    def api(self,path,data,token='w'*48):
        return Client(enforce_csrf_checks=True).post('/api/eta/v1/'+path,data=json.dumps(data),content_type='application/json',HTTP_AUTHORIZATION='Bearer '+token)
    def ready_submission(self):
        batch=self.queue();job=self.claim()
        eta_transport.receive_result(self.app.pk,'worker-1',job['lease_token'],self.result(batch))
        self.app.refresh_from_db()
        response=self.client.post(reverse('eta_authorize',args=[self.contract.pk,self.app.pk]),{'version':str(self.app.updated_at),'summary_reviewed':'on','address_reviewed':'on','conditions_confirmed':'on','fee':'0.00','currency':'USD'})
        self.assertEqual(response.status_code,302);self.app.refresh_from_db()
        return batch,self.claim()
    def begin(self,job,fee=None):
        self.app.refresh_from_db();context=eta.authorization_context(self.app)
        return eta_transport.begin_submission(self.app.pk,'worker-1',job['lease_token'],context['review_sha256'],context['conditions_sha256'],fee or {'amount':'0.00','currency':'USD'})
    def message(self,kind='ETA APPROVAL NOTICE',number='TEST-ETA-100',passport='TEST000001',surname='EXAMPLE',given='TEST',body_extra='',auth=''):
        m=EmailMessage();m['From']='no-reply@official.example.invalid';m['To']=eta.EMAIL;m['Subject']=kind
        if auth:m['Authentication-Results']=auth
        m.set_content(f'{kind}\nETA Number: {number}\nPassport Number: {passport}\nSurname: {surname}\nGiven Names: {given}\n{body_extra}')
        return m.as_bytes()
    def submitted(self):
        self.app.active_export=self.export();self.app.status='submitted';self.app.application_number='TEST-ETA-100';self.app.submission_authorized_at=timezone.now();self.app.submission_started_at=timezone.now();self.app.save()

    def test_enqueue_same_batch_no_duplicate_restart(self):
        batch=self.queue();job=self.claim()
        self.assertEqual(self.queue().pk,batch.pk)
        self.assertEqual(ETAApplication.objects.count(),1);self.assertIsNone(self.claim())
        self.app.refresh_from_db();self.assertEqual(self.app.transport_state,'leased')
        self.assertEqual(job['packet']['schema'],eta.SCHEMA)
    def test_api_bearer_roles_and_no_csrf_session_fallback(self):
        self.queue()
        self.assertEqual(self.api('claim/',{'worker_id':'worker-1'},token='m'*48).status_code,401)
        self.assertEqual(self.api('claim/',{'worker_id':'worker-1'}).status_code,200)
        self.assertEqual(self.api('mail/',{'eml_base64':''}).status_code,401)
    def test_cross_worker_or_wrong_lease_rejected(self):
        self.queue();job=self.claim()
        with self.assertRaises(ValidationError):eta_transport.heartbeat(self.app.pk,'other',job['lease_token'])
        with self.assertRaises(ValidationError):eta_transport.heartbeat(self.app.pk,'worker-1','wrong')
    def test_expired_submission_not_reclaimed(self):
        _,job=self.ready_submission();self.begin(job)
        ETAApplication.objects.filter(pk=self.app.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        recovered=self.claim();self.app.refresh_from_db()
        self.assertEqual(recovered['action'],'status');self.assertIn('неизвестен',self.app.stop_reason)
    def test_begin_requires_human_authorization_and_only_once(self):
        self.queue();job=self.claim()
        with self.assertRaises(ValidationError):eta_transport.begin_submission(self.app.pk,'worker-1',job['lease_token'],'a','b',{})
        batch=self.app.active_export
        # complete a fresh independent approved summary flow
        self.app.refresh_from_db();eta_transport.receive_result(self.app.pk,'worker-1',job['lease_token'],self.result(self.app.active_export))
        self.app.refresh_from_db();self.client.post(reverse('eta_authorize',args=[self.contract.pk,self.app.pk]),{'version':str(self.app.updated_at),'summary_reviewed':'on','address_reviewed':'on','conditions_confirmed':'on','fee':'0.00','currency':'USD'})
        submit=self.claim();self.begin(submit)
        with self.assertRaises(ValidationError):self.begin(submit)
    def test_fee_change_and_crm_change_block_final_click(self):
        _,job=self.ready_submission()
        with self.assertRaises(ValidationError):self.begin(job,{'amount':'50.00','currency':'USD'})
        self.contract.hotel='CHANGED HOTEL';self.contract.save()
        with self.assertRaises(ValidationError):self.begin(job)
    def test_return_blocked_while_executor_holds_lease(self):
        self.queue();self.claim();self.app.refresh_from_db()
        self.client.post(reverse('eta_return',args=[self.contract.pk,self.app.pk]),{'version':str(self.app.updated_at),'portal_checked_no_submission':'on','reason':'Test return'})
        self.app.refresh_from_db();self.assertIsNotNone(self.app.active_export_id)
    def test_manual_status_after_uncertain_never_schedules_submit(self):
        _,job=self.ready_submission();self.begin(job)
        self.app.refresh_from_db();self.app.transport_state='stopped';self.app.save()
        eta_transport.schedule_status(self.app,self.user);self.app.refresh_from_db()
        self.assertEqual(self.app.transport_action,'status');self.assertEqual(self.app.transport_state,'queued')
    def test_session_capacity_does_not_evict_waiting_forms(self):
        self.queue();self.assertIsNone(eta_transport.claim('worker-1',[],False))
        self.assertIsNotNone(eta_transport.claim('worker-1',[str(self.app.pk)],False))
    def test_mail_missing_trust_goes_to_review_then_owner_accepts(self):
        self.submitted();notice=eta_mail.ingest(self.message())
        self.app.refresh_from_db();self.assertEqual(self.app.status,'submitted');self.assertIsNone(notice.accepted_at)
        eta_mail.accept_notice(notice,self.user);self.app.refresh_from_db();self.assertEqual(self.app.status,'approved')
    @override_settings(ETA_MAIL_AUTOMATIC_TRUST=True,ETA_MAIL_OFFICIAL_DOMAINS=('official.example.invalid',),ETA_MAIL_AUTHSERV_ID='mx.test.invalid')
    def test_trusted_approval_and_idempotence(self):
        self.submitted();raw=self.message(auth='mx.test.invalid; dkim=pass header.d=official.example.invalid')
        notice=eta_mail.ingest(raw);again=eta_mail.ingest(raw)
        self.app.refresh_from_db();self.assertEqual(self.app.status,'approved');self.assertEqual(notice.pk,again.pk);self.assertEqual(ETAOfficialNotice.objects.count(),1)
    @override_settings(ETA_MAIL_AUTOMATIC_TRUST=True,ETA_MAIL_OFFICIAL_DOMAINS=('official.example.invalid',),ETA_MAIL_AUTHSERV_ID='mx.test.invalid')
    def test_forged_auth_header_deeper_in_message_not_trusted(self):
        self.submitted();m=EmailMessage();m['From']='no-reply@official.example.invalid';m['Subject']='ETA APPROVAL NOTICE'
        m['Authentication-Results']='mx.test.invalid; dkim=fail header.d=official.example.invalid'
        m['Authentication-Results']='mx.test.invalid; dkim=pass header.d=official.example.invalid'
        m.set_content('ETA APPROVAL NOTICE\nETA Number: TEST-ETA-100\nPassport Number: TEST000001\nSurname: EXAMPLE\nGiven Names: TEST')
        n=eta_mail.ingest(m.as_bytes());self.assertFalse(n.trusted);self.assertIsNone(n.accepted_at)
    def test_receipt_never_approval(self):
        self.submitted();notice=eta_mail.ingest(self.message(kind='ETA APPLICATION RECEIVED'))
        eta_mail.accept_notice(notice,self.user);self.app.refresh_from_db();self.assertEqual(self.app.status,'under_review')
    def test_referral_distinct_from_approval(self):
        self.submitted();notice=eta_mail.ingest(self.message(kind='ETA REFERRED'))
        eta_mail.accept_notice(notice,self.user);self.app.refresh_from_db();self.assertEqual(self.app.status,'referral')
    def test_wrong_passport_and_unknown_layout_not_bound(self):
        self.submitted();notice=eta_mail.ingest(self.message(passport='OTHER000'))
        self.assertIsNone(notice.application_id)
        with self.assertRaises(ValidationError):eta_mail.accept_notice(notice,self.user)
    def test_dependent_child_does_not_receive_mothers_approval(self):
        self.submitted();child=self.make_tourist('CHILD','2020-01-01','CHILD12345');child_app=self.make_app(child)
        notice=eta_mail.ingest(self.message(body_extra='Dependents\nETA Number: CHILD-NUM\nPassport Number: CHILD12345\nSurname: CHILD\nGiven Names: TEST'))
        eta_mail.accept_notice(notice,self.user);child_app.refresh_from_db();self.assertEqual(child_app.status,'ready');self.assertEqual(notice.application_id,self.app.pk)
    def test_unsafe_html_is_escaped_and_pdf_is_copy_of_real_evidence(self):
        self.submitted();m=EmailMessage();m['Subject']='ETA';m['From']='test@example.invalid'
        m.set_content('<html><script>SECRET SCRIPT</script><p>Official test text</p><img src="https://evil.invalid/pixel"><p>&lt;script&gt;literal&lt;/script&gt;</p></html>',subtype='html')
        n=eta_mail.ingest(m.as_bytes());self.assertNotIn('SECRET SCRIPT',n.safe_text);self.assertNotIn('evil.invalid',n.safe_text)
        response=self.client.get(reverse('eta_notice',args=[n.pk]));self.assertContains(response,'&lt;script&gt;literal&lt;/script&gt;',html=False)
        self.assertTrue(eta_mail.pdf_copy(n).startswith(b'%PDF-'))
    def test_notice_download_requires_permissions_and_is_attachment(self):
        self.submitted();n=eta_mail.ingest(self.message())
        url=reverse('eta_notice_document',args=[n.pk,'eml'])
        self.assertEqual(Client().get(url).status_code,302)
        response=self.client.get(url);self.assertIn('attachment',response['Content-Disposition']);self.assertEqual(b''.join(response.streaming_content),bytes(n.original))
    def test_background_ui_hides_file_exchange_in_reserve(self):
        response=self.client.get(self.url);self.assertContains(response,'Оформить ETA — запустить')
        self.assertContains(response,'Резервный обмен файлами')

    def test_receipt_can_recover_number_after_uncertain_submission(self):
        self.submitted();self.app.application_number='';self.app.status='error';self.app.save()
        n=eta_mail.ingest(self.message(kind='ETA APPLICATION RECEIVED'))
        eta_mail.accept_notice(n,self.user);self.app.refresh_from_db()
        self.assertEqual(self.app.application_number,'TEST-ETA-100');self.assertEqual(self.app.status,'under_review')
    def test_receipt_arriving_late_does_not_downgrade_referral(self):
        self.submitted();self.app.status='referral';self.app.save()
        n=eta_mail.ingest(self.message(kind='ETA APPLICATION RECEIVED'))
        eta_mail.accept_notice(n,self.user);self.app.refresh_from_db();self.assertEqual(self.app.status,'referral')

    def test_revoked_session_is_released_without_reusing_old_browser(self):
        self.queue();self.claim()
        response=self.api('sessions/',{'worker_id':'worker-1','applications':[str(self.app.pk)]})
        self.assertEqual(response.json()['keep'],[str(self.app.pk)])
        ETAApplication.objects.filter(pk=self.app.pk).update(worker_id='',active_export=None,transport_state='manual')
        response=self.api('sessions/',{'worker_id':'worker-1','applications':[str(self.app.pk)]})
        self.assertEqual(response.json()['keep'],[])
