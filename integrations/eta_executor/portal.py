"""Playwright portal driver with an operator-verified declarative field map.
No guessed live selectors; an unknown field or unverified map always stops.
"""
import copy
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from urllib.parse import urlsplit


class PortalStop(Exception):
    def __init__(self,reason,captcha=False,changed=False):
        super().__init__(reason);self.captcha=captcha;self.changed=changed


def get(data,path):
    for part in path.split('.'):data=data[part]
    return data


def put(data,path,value):
    bits=path.split('.')
    for part in bits[:-1]:data=data.setdefault(part,{})
    data[bits[-1]]=value


def digest(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


def leaves(value,prefix=''):
    if isinstance(value,dict):
        for key,item in value.items():yield from leaves(item,(prefix+'.' if prefix else '')+key)
    else:yield prefix,value


class Portal:
    def __init__(self,page,mapping,dry_run=True,test_mode=False):
        self.page=page;self.mapping=mapping;self.dry_run=dry_run;self.test_mode=test_mode
        if mapping.get('verified') is not True or not mapping.get('verified_at') or not mapping.get('version'):
            raise PortalStop('Разметка официального портала не проверена. Нужна настройка и контрольный просмотр.',changed=True)
        self.hosts=set(mapping.get('allowed_hosts',[]))
        if not self.hosts or (not test_mode and any(h not in ('eta.gov.lk','www.eta.gov.lk') for h in self.hosts)):
            raise PortalStop('Непроверенный адрес официального портала.',changed=True)
        self.page.set_default_timeout(10000)
    def check_url(self,url):
        value=urlsplit(url)
        if value.hostname not in self.hosts or (value.scheme!='https' and not self.test_mode):raise PortalStop('Переход за пределы разрешённого официального портала остановлен.',changed=True)
    async def guard(self,route):
        url=route.request.url
        if url.startswith('data:'):await route.continue_();return
        value=urlsplit(url)
        # Block third-party posts and external scripts/frames; map must be reviewed
        # before extending this allowlist for any official portal infrastructure.
        if value.hostname not in self.hosts or (value.scheme!='https' and not self.test_mode):await route.abort();return
        await route.continue_()
    async def read(self,spec):
        locator=self.page.locator(spec['selector'])
        if await locator.count()!=1:raise PortalStop('Структура официальной формы изменилась.',changed=True)
        if spec.get('attribute')=='value':value=await locator.input_value()
        else:value=(await locator.inner_text()).strip()
        kind=spec.get('type','str')
        try:
            if kind=='int':return int(value)
            if kind=='bool':
                if value.lower() not in ('yes','no','true','false'):raise ValueError()
                return value.lower() in ('yes','true')
            if kind=='iso_date':return datetime.strptime(value,self.mapping.get('date_format','%m-%d-%Y')).date().isoformat()
            if kind=='json':return json.loads(value)
            return value
        except (ValueError,TypeError):raise PortalStop('Невозможно проверить фактическое значение поля.',changed=True) from None
    async def check_blockers(self):
        self.check_url(self.page.url)
        common=self.page.locator('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],input[name*="captcha" i],[data-sitekey]')
        for control in await common.all():
            if await control.is_visible():raise PortalStop('Требуется CAPTCHA в сохранённом браузере исполнителя.',captcha=True)
        for spec in self.mapping.get('blockers',[]):
            locator=self.page.locator(spec['selector'])
            if await locator.count() and await locator.first.is_visible():
                kind=spec.get('kind','unknown')
                raise PortalStop({'captcha':'Требуется CAPTCHA в сохранённом браузере исполнителя.','existing_visa':'Портал сообщил о существующей визе/ETA; нужна проверка.','unknown':'Портал требует уточнения сведений.'}.get(kind,'Нужно участие пользователя.'),captcha=kind=='captcha',changed=kind=='unknown')
    async def check_controls(self,step):
        allowed=set(step.get('ignored_hidden_names',[]))
        known=set()
        for spec in step.get('fields',[]):
            loc=self.page.locator(spec['selector'])
            if await loc.count()!=1:raise PortalStop('Поле официальной формы отсутствует или повторяется.',changed=True)
            # Compare actual DOM nodes, not just names (several controls may share a name).
            marker='eta-known-'+hashlib.sha256(spec['selector'].encode()).hexdigest()[:16]
            await loc.evaluate('(el, marker) => el.setAttribute("data-eta-known", marker)',marker);known.add(marker)
        for control in await self.page.locator('input,select,textarea').all():
            kind=(await control.get_attribute('type') or '').lower()
            if kind in ('submit','button','reset'):continue
            if await control.get_attribute('data-eta-known') in known:continue
            if kind=='hidden' and await control.get_attribute('name') in allowed:continue
            if kind=='hidden' or await control.is_visible():raise PortalStop('Обнаружено неизвестное поле официальной анкеты. Нужна проверка.',changed=True)
    def portal_value(self,data,spec):
        value=get(data,spec['path'])
        if spec.get('date'):value=datetime.strptime(value,'%Y-%m-%d').strftime(self.mapping.get('date_format','%m-%d-%Y'))
        if 'values' in spec:
            value=spec['values'].get(str(value))
            if value is None:raise PortalStop('Значение отсутствует в проверенном справочнике портала.')
        return str(value)
    async def prepare(self,data):
        if self.page.url=='about:blank':
            self.check_url(self.mapping['start_url']);await self.page.goto(self.mapping['start_url'],wait_until='domcontentloaded')
        await self.check_blockers()
        # A retained session may already be on its summary screen after CAPTCHA.
        if self.mapping.get('summary_marker') and await self.page.locator(self.mapping['summary_marker']).count() and await self.page.locator(self.mapping['summary_marker']).is_visible():return await self.summary(data)
        for step in self.mapping.get('steps',[]):
            if not await self.page.locator(step['marker']).count() or not await self.page.locator(step['marker']).is_visible():continue
            await self.check_blockers();await self.check_controls(step)
            for spec in step.get('fields',[]):
                value=self.portal_value(data,spec);field=self.page.locator(spec['selector']);kind=spec.get('kind','text')
                if kind=='select':await field.select_option(value=value)
                elif kind=='checkbox':await field.set_checked(value.lower() in ('true','yes','1'))
                elif kind=='radio':await field.check()
                else:
                    await field.fill('');await field.press_sequentially(value,delay=20);await field.press('Tab')
                actual=str(await field.is_checked()).lower() if kind in ('checkbox','radio') else await field.input_value()
                expected=value.lower() if kind in ('checkbox','radio') else value
                if actual!=expected:raise PortalStop('Портал не сохранил введённое значение. Нужна проверка.')
            if step.get('next'):
                # Field map has to certify this is navigation, never a submit/payment.
                if step.get('navigation_only') is not True:raise PortalStop('Переход не подтверждён как безопасная навигация.',changed=True)
                await self.page.locator(step['next']).click();await self.page.wait_for_timeout(300)
        await self.check_blockers()
        return await self.summary(data)
    async def summary(self,data):
        await self.check_blockers()
        if not self.mapping.get('summary_marker') or not await self.page.locator(self.mapping['summary_marker']).count() or not await self.page.locator(self.mapping['summary_marker']).is_visible():raise PortalStop('Фактическая сводка портала ещё не доступна.')
        # Every row of the actual review screen must be recognised, not just
        # the subset of fields the old map happened to know about.
        if not self.mapping.get('summary_items'):raise PortalStop('Не задана проверка новых строк фактической сводки.',changed=True)
        for spec in self.mapping.get('summary',[]):
            await self.page.locator(spec['selector']).evaluate('(el) => el.setAttribute("data-eta-reviewed", "1")')
        for item in await self.page.locator(self.mapping['summary_items']).all():
            if await item.is_visible() and await item.get_attribute('data-eta-reviewed')!='1':raise PortalStop('В фактической сводке появилось неизвестное поле.',changed=True)
        summary={}
        for spec in self.mapping.get('summary',[]):put(summary,spec['path'],await self.read(spec))
        # CRM context metadata has no corresponding portal field. Identity, contact,
        # dates, passport and answers MUST all be read back from the actual page.
        summary.setdefault('person',{})['age_on_arrival']=data['person']['age_on_arrival']
        summary.setdefault('passport',{})['own']=True
        summary['child']=copy.deepcopy(data['child'])
        for group in ('person','passport','home','travel','accommodation','contact'):
            if group not in summary or set(summary[group])!=set(data[group]):raise PortalStop('Сводка не содержит все проверяемые сведения: '+group,changed=True)
        if 'additional_fields' not in summary:raise PortalStop('Не проверены дополнительные/скрытые поля сводки.',changed=True)
        terms=await self.read(self.mapping['conditions'])
        amount=await self.read(self.mapping['fee_amount']);currency=await self.read(self.mapping['fee_currency'])
        try:
            if not re.fullmatch(r'\d+(?:\.\d{1,2})?',amount):raise ValueError()
            amount=str(Decimal(amount).quantize(Decimal('.01')))
            if not re.fullmatch('[A-Z]{3}',currency):raise ValueError()
        except (ValueError,ArithmeticError):raise PortalStop('Фактический сбор не определён однозначно.') from None
        return {'portal_summary':summary,'portal_conditions':{'text':terms,'sha256':hashlib.sha256(terms.encode()).hexdigest()},
                'fee':{'amount':amount,'currency':currency},'hotel_address_source':self.mapping.get('hotel_address_source',''),
                'captcha_required':False,'portal_rules_changed':False,'unconfirmed_fields':[]}
    async def submit(self,data,begin):
        if self.dry_run:raise PortalStop('Тестовый режим: окончательная подача отключена.')
        actual=await self.summary(data)
        # Persist the one-use server fence immediately before the final click.
        authorization=await begin(digest(actual['portal_summary']),actual['portal_conditions']['sha256'],actual['fee'])
        await self.page.locator(self.mapping['submit']).click(timeout=15000)
        await self.page.wait_for_timeout(500)
        await self.check_blockers()
        number=await self.read(self.mapping['application_number']);status=await self.read(self.mapping['portal_status'])
        if not number:raise PortalStop('Результат подачи неизвестен. Повтор запрещён.')
        return {**actual,'application_number':number,'portal_status':status,'authorization_token':authorization['authorization_token'],'stage':'submitted'}
    async def status(self,number,data):
        # This path cannot navigate to or click the application submission button.
        spec=self.mapping.get('status')
        if not spec:raise PortalStop('Проверка статуса портала ещё не настроена. Повторная подача не выполняется.')
        self.check_url(spec['url']);await self.page.goto(spec['url'],wait_until='domcontentloaded');await self.check_blockers()
        if not number:raise PortalStop('Номер ETA неизвестен: проверьте принятие в сохранённой сессии и почту. Повтор запрещён.')
        status_fields=spec.get('fields',[])
        await self.check_controls({'fields':[{'selector':spec['number_input']},*status_fields],'ignored_hidden_names':spec.get('ignored_hidden_names',[])})
        await self.page.locator(spec['number_input']).fill(number)
        for field in status_fields:
            value=self.portal_value(data,field);control=self.page.locator(field['selector'])
            if field.get('kind')=='select':await control.select_option(value=value)
            else:await control.fill('');await control.press_sequentially(value,delay=20);await control.press('Tab')
            if await control.input_value()!=value:raise PortalStop('Не подтверждено значение поля проверки статуса.')
        await self.page.locator(spec['check']).click();await self.check_blockers()
        actual_number=await self.read(spec['application_number'])
        if actual_number!=number:raise PortalStop('Портал вернул другой номер ETA.')
        for key,expected in (('passport',data['passport']['number']),('surname',data['person']['surname']),('given_names',data['person']['given_names'])):
            if key not in spec or re.sub(r'[^a-z0-9]','',(await self.read(spec[key])).lower())!=re.sub(r'[^a-z0-9]','',expected.lower()):
                raise PortalStop('Не подтверждены паспорт и ФИО основного заявителя в ответе статуса.')
        status=await self.read(spec['portal_status'])
        stage=spec.get('states',{}).get(status)
        if stage not in ('under_review','approved','referral'):raise PortalStop('Неизвестный фактический статус портала.',changed=True)
        result={'stage':stage,'application_number':number,'portal_status':status,'captcha_required':False,'portal_rules_changed':False,'unconfirmed_fields':[]}
        if stage=='referral':result['stop_reason']='Портал направил заявление на дополнительное рассмотрение.'
        if stage=='approved':
            # Fetch only the configured official PDF, never generate an "approval".
            if not spec.get('approval_pdf'):raise PortalStop('Статус одобрен, но официальный Approval Notice ещё не доступен.')
            locator=self.page.locator(spec['approval_pdf']);href=await locator.get_attribute('href')
            from urllib.parse import urljoin
            url=urljoin(self.page.url,href or '');self.check_url(url)
            response=await self.page.request.get(url,max_redirects=0)
            body=await response.body()
            if not response.ok or not body.startswith(b'%PDF-') or len(body)>5*1024*1024:raise PortalStop('Официальный документ одобрения не получен как PDF.')
            import base64
            result.update(approval_confirmed=True,approval_notice={'mime_type':'application/pdf','sha256':hashlib.sha256(body).hexdigest(),'content_base64':base64.b64encode(body).decode()})
        return result
