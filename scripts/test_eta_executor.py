"""Local synthetic pages ONLY. python -m unittest scripts.test_eta_executor -v"""
import asyncio
import copy
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from integrations.eta_executor.portal import Portal,PortalStop,leaves

DATA=json.loads(Path('docs/examples/eta-job-v1.json').read_text())['applicants'][0]['data']
# Use structured synthetic data, no real persons or production domain.
DATA=copy.deepcopy(DATA);DATA['home']={'address':'1 Example Road','city':'Test City','region':'Test Region','country':'Test Country'};DATA['accommodation']['full_address']='1 Test Hotel Road'
PAIRS=[(path,value) for group in ('person','passport','home','contact','travel','accommodation') for path,value in leaves(DATA[group],group) if path not in ('person.age_on_arrival','passport.own')]


def fixture():
    from html import escape
    inputs=''.join(f'<input id="field-{i}" name="field-{i}">' for i,_ in enumerate(PAIRS))
    summary=''.join(f'<span class="summary-item" id="summary-{i}"></span>' for i,_ in enumerate(PAIRS))
    return f'''<!doctype html><h1>SYNTHETIC ETA TEST ONLY</h1><form id="application">{inputs}<button id="next" type="button">Review</button></form><section id="summary" style="display:none">{summary}<span id="additional" class="summary-item">{{}}</span><p id="terms">Fictional test terms only.</p><span id="fee">0.00</span><span id="currency">USD</span><button type="button" id="submit">Synthetic submit</button></section><div id="captcha" style="display:none">CAPTCHA</div><span id="clicked">0</span><span id="number"></span><span id="status"></span><script>
next.onclick=()=>{{document.querySelectorAll('#application input').forEach((e,i)=>document.querySelector('#summary-'+i).textContent=e.value);document.querySelector('#application').style.display='none';document.querySelector('#summary').style.display='block'}};
document.querySelector('#submit').onclick=()=>{{document.querySelector('#clicked').textContent='1';document.querySelector('#number').textContent='TEST-ETA-100';document.querySelector('#status').textContent='Received'}};
</script>'''.encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/status':
            page=b'''<!doctype html><h1>SYNTHETIC STATUS ONLY</h1><input id="status-number"><input id="status-passport"><button id="status-check">Check</button><span id="out-number"></span><span id="out-passport"></span><span id="out-surname">EXAMPLE</span><span id="out-given">TEST</span><span id="out-status">Under review</span><script>document.querySelector('#status-check').onclick=()=>{document.querySelector('#out-number').textContent=document.querySelector('#status-number').value;document.querySelector('#out-passport').textContent=document.querySelector('#status-passport').value};</script>'''
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(page);return
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(fixture())
    def log_message(self,*args):pass


class PortalTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch(executable_path=os.getenv('ETA_TEST_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
        self.context=await self.browser.new_context();self.page=await self.context.new_page()
        fields=[{'path':path,'selector':f'#field-{i}'} for i,(path,_) in enumerate(PAIRS)]
        summary=[{'path':path,'selector':f'#summary-{i}'} for i,(path,_) in enumerate(PAIRS)]+[{'path':'additional_fields','selector':'#additional','type':'json'}]
        self.mapping={'version':'synthetic-only','verified':True,'verified_at':'2026-10-30','allowed_hosts':['127.0.0.1'],'start_url':f'http://127.0.0.1:{self.server.server_port}/',
          'steps':[{'marker':'#application','fields':fields,'next':'#next','navigation_only':True}], 'summary_marker':'#summary','summary_items':'.summary-item','summary':summary,
          'conditions':{'selector':'#terms'},'fee_amount':{'selector':'#fee'},'fee_currency':{'selector':'#currency'},'submit':'#submit',
          'application_number':{'selector':'#number'},'portal_status':{'selector':'#status'},'blockers':[{'selector':'#captcha','kind':'captcha'}]}
        self.driver=Portal(self.page,self.mapping,dry_run=False,test_mode=True)
    async def asyncTearDown(self):await self.browser.close();await self.playwright.stop()
    async def test_keyboard_fill_and_actual_summary(self):
        actual=await self.driver.prepare(DATA)
        self.assertEqual(actual['portal_summary']['passport']['number'],DATA['passport']['number'])
        self.assertEqual(actual['portal_summary']['travel']['arrival_date'],DATA['travel']['arrival_date'])
        self.assertEqual(await self.page.locator('#clicked').inner_text(),'0')
    async def test_final_action_checks_online_authorization_before_click(self):
        await self.driver.prepare(DATA)
        async def denied(*args):
            self.assertEqual(await self.page.locator('#clicked').inner_text(),'0')
            raise PortalStop('Permission revoked')
        with self.assertRaisesRegex(PortalStop,'Permission revoked'):await self.driver.submit(DATA,denied)
        self.assertEqual(await self.page.locator('#clicked').inner_text(),'0')
    async def test_summary_remains_in_same_live_session_until_confirmation(self):
        await self.driver.prepare(DATA);await self.page.evaluate('window.syntheticSessionValue=42')
        async def authorized(review,conditions,fee):
            self.assertEqual(await self.page.evaluate('window.syntheticSessionValue'),42);self.assertEqual(fee,{'amount':'0.00','currency':'USD'})
            return {'authorization_token':'synthetic-token-only'}
        result=await self.driver.submit(DATA,authorized)
        self.assertEqual(result['application_number'],'TEST-ETA-100');self.assertEqual(await self.page.locator('#clicked').inner_text(),'1')
    async def test_dry_run_never_clicks(self):
        await self.driver.prepare(DATA);self.driver.dry_run=True
        with self.assertRaises(PortalStop):await self.driver.submit(DATA,None)
        self.assertEqual(await self.page.locator('#clicked').inner_text(),'0')
    async def test_unknown_control_stops(self):
        await self.page.goto(self.mapping['start_url']);await self.page.evaluate('document.querySelector("#application").insertAdjacentHTML("beforeend", "<input name=unexpected>")')
        with self.assertRaises(PortalStop):await self.driver.prepare(DATA)
    async def test_new_summary_field_and_captcha_stop(self):
        await self.driver.prepare(DATA)
        await self.page.evaluate('document.querySelector("#summary").insertAdjacentHTML("beforeend", "<span class=summary-item>Unknown vaccination answer</span>")')
        with self.assertRaises(PortalStop):await self.driver.summary(DATA)
        await self.page.locator('#captcha').evaluate('(el)=>el.style.display="block"')
        with self.assertRaises(PortalStop) as caught:await self.driver.summary(DATA)
        self.assertTrue(caught.exception.captcha)
    async def test_unverified_live_map_rejected(self):
        mapping=copy.deepcopy(self.mapping);mapping['verified']=False
        with self.assertRaises(PortalStop):Portal(self.page,mapping,test_mode=True)
    async def test_changed_fee_is_read_again_at_final_check(self):
        await self.driver.prepare(DATA);await self.page.locator('#fee').evaluate('(el)=>el.textContent="50.00"')
        async def denied(review,conditions,fee):
            self.assertEqual(fee['amount'],'50.00');raise PortalStop('Unexpected fee')
        with self.assertRaises(PortalStop):await self.driver.submit(DATA,denied)
        self.assertEqual(await self.page.locator('#clicked').inner_text(),'0')

    async def test_status_path_uses_prior_number_and_passport_without_new_application(self):
        data=copy.deepcopy(DATA);data['person']['surname']='EXAMPLE';data['person']['given_names']='TEST'
        self.mapping['status']={'url':f'http://127.0.0.1:{self.server.server_port}/status','number_input':'#status-number','check':'#status-check',
            'fields':[{'path':'passport.number','selector':'#status-passport'}],
            'application_number':{'selector':'#out-number'},'passport':{'selector':'#out-passport'},'surname':{'selector':'#out-surname'},'given_names':{'selector':'#out-given'},
            'portal_status':{'selector':'#out-status'},'states':{'Under review':'under_review'}}
        result=await self.driver.status('TEST-ETA-100',data)
        self.assertEqual(result['stage'],'under_review');self.assertTrue(self.page.url.endswith('/status'))
        self.assertEqual(await self.page.locator('#submit').count(),0)
        data['person']['surname']='OTHER'
        with self.assertRaises(PortalStop):await self.driver.status('TEST-ETA-100',data)
