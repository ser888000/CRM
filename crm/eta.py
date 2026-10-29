"""ETA file exchange only. This module never contacts or submits to a portal."""
import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_variables
from .models import Tourist, ETAApplication, ETAExport, AuditEvent

EMAIL='spo-ab@ya.ru'
PORTAL='https://www.eta.gov.lk/slvisa/'
SCHEMA='aborigen.sri-lanka-eta.job.v1'
RESULT_SCHEMA='aborigen.sri-lanka-eta.result.v1'
READ_PERMS=('crm.view_contract','crm.view_tourist','crm.view_customer','crm.view_etaapplication')
SUMMARY_GROUPS=('person','passport','home','travel','accommodation','contact','child')
SENT={'submitted','under_review','approved','referral'}
TRANSITIONS={
 'ready':{'ready','filling','needs_data','awaiting_confirmation','referral','error'},
 'filling':{'filling','needs_data','awaiting_confirmation','referral','error'},
 'awaiting_confirmation':{'awaiting_confirmation','filling','submitted','needs_data','referral','error'},
 'submitted':{'submitted','under_review','approved','referral','error'},
 'under_review':{'under_review','approved','referral','error'},
 'approved':{'approved'},'referral':{'referral','under_review','approved','error'},
 'error':{'error','needs_data','awaiting_confirmation','submitted','under_review','approved','referral'},
 'needs_data':{'needs_data','error','awaiting_confirmation'},
}


def canonical(data):return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
def digest(data):return hashlib.sha256(canonical(data).encode()).hexdigest()
def linked(contract):return Tourist.objects.filter(contractline__contract=contract).distinct().order_by('pk')
def iso(value):return value.isoformat() if isinstance(value,date) else value or ''
def age_on(birthday,day):return day.year-birthday.year-((day.month,day.day)<(birthday.month,birthday.day))
def normalized(value):return re.sub(r'[^a-zа-яё0-9]','',str(value).casefold())

def identity_country(value):
    key=normalized(value)
    return 'ru' if key in ('ru','rus','russia','russianfederation','россия','российскаяфедерация','643') else key


def source_hash(contract,tourist):
    fields=('surname','given_name','name','gender','birthday','birthcountry','nationality','passport_type','passport_number','issued','expires')
    return digest({'tourist':{key:getattr(tourist,key) for key in fields},
        'contract':{key:getattr(contract,key) for key in ('country','start','end','hotel','flights','source_data')},
        'payer_contact':{'address':contract.customer.address,'phone':contract.customer.main_phone,'phones':contract.customer.phones},
        'snapshots':list(contract.lines.filter(tourist=tourist).values_list('tourist_snapshot',flat=True))})


def source_date(value):
    from datetime import datetime
    for pattern in ('%Y-%m-%d','%d.%m.%Y'):
        try:return datetime.strptime(str(value),pattern).date().isoformat()
        except ValueError:pass
    return ''


def initial_data(contract,tourist):
    data=dict(surname=tourist.surname,given_names=tourist.given_name,gender=tourist.gender,
        birthday=iso(tourist.birthday),nationality=tourist.nationality,birth_country=tourist.birthcountry,
        passport_type=tourist.passport_type,passport_number=tourist.passport_number,
        passport_issued=iso(tourist.issued),passport_expires=iso(tourist.expires),hotel_name=contract.hotel,
        home_address=contract.customer.address,phone=contract.customer.main_phone or contract.customer.phones,
        travel_last_14_days='Россия',own_passport='yes' if tourist.passport_type=='0' and tourist.passport_number else '')
    flights=contract.source_data.get('transport',[])
    flights=flights if isinstance(flights,list) else []
    arrivals=[f for f in flights if isinstance(f,dict) and str(f.get('terminalcodeto','')).upper() in ('CMB','HRI','JAF')]
    if len(arrivals)==1:
        f=arrivals[0]
        data.update(arrival_date=source_date(f.get('dateto')),departure_airport=f.get('terminalcodefrom',''),
            arrival_airport=f.get('terminalcodeto',''),airline=f.get('aircompany',''),flight_number=f.get('number',''))
    departures=[f for f in flights if isinstance(f,dict) and str(f.get('terminalcodefrom','')).upper() in ('CMB','HRI','JAF')]
    if len(departures)==1:data['departure_date']=source_date(departures[0].get('datefrom'))
    hotels=contract.source_data.get('hotel',[])
    if isinstance(hotels,list) and len(hotels)==1 and isinstance(hotels[0],dict):
        hotel=hotels[0]
        if not data['hotel_name']:data['hotel_name']=hotel.get('name','')
        if normalized(hotel.get('name',''))==normalized(data['hotel_name']):data['hotel_address']=hotel.get('address','')
    # Agency policy explicitly uses the payer address and phone for ETA contact details.
    return data


@sensitive_variables()
def assess(application,preparation=None):
    p=preparation if preparation is not None else application.preparation
    issues=[]
    required={'surname':'Фамилия латиницей','given_names':'Имена латиницей','gender':'Пол','birthday':'Дата рождения',
        'nationality':'Гражданство','birth_country':'Страна рождения','home_address':'Домашний адрес',
        'phone':'Телефон туриста','arrival_date':'Дата прибытия в Шри-Ланку','departure_date':'Дата выезда',
        'departure_airport':'Аэропорт вылета','arrival_airport':'Аэропорт прибытия','airline':'Авиакомпания',
        'flight_number':'Номер прибывающего рейса','hotel_name':'Отель',
        'previous_visas':'Сведения о предыдущих визах',
        'travel_last_14_days':'История пребывания за последние 14 дней'}
    for key,label in required.items():
        if not p.get(key):issues.append('Не заполнено: '+label)
    for key in ('surname','given_names'):
        if p.get(key) and not re.fullmatch(r"[A-Za-z][A-Za-z '\-]*",p[key]):issues.append('ФИО должны быть латиницей строго по загранпаспорту, без автоматического перевода.')
    phone=re.sub(r'[\s()\-]','',p.get('phone',''))
    if phone and not re.fullmatch(r'\+[1-9][0-9]{6,14}',phone):issues.append('Телефон нужен в международном формате с кодом страны.')
    for key in ('departure_airport','arrival_airport'):
        if p.get(key) and not re.fullmatch(r'[A-Z]{3}',p[key]):issues.append('Аэропорты указываются трёхбуквенным кодом IATA.')
    if p.get('arrival_airport') and p['arrival_airport'] not in ('CMB','HRI','JAF'):issues.append('Проверьте, что выбран именно аэропорт прибытия в Шри-Ланку.')
    def day(key):
        try:return date.fromisoformat(p.get(key,''))
        except (ValueError,TypeError):return None
    birth,arrival,departure,issued,expiry=[day(k) for k in ('birthday','arrival_date','departure_date','passport_issued','passport_expires')]
    age=age_on(birth,arrival) if birth and arrival else None
    if age is not None and age<0:issues.append('Дата рождения позже прибытия.')
    if arrival and arrival<timezone.localdate():issues.append('Дата прибытия уже прошла. Проверьте новую поездку.')
    if arrival and departure and departure<arrival:issues.append('Выезд раньше прибытия.')
    own=True
    if p.get('own_passport','yes')!='yes':issues.append('Этот этап поддерживает только отдельные заявления по собственному загранпаспорту.')
    if own:
        for key,label in [('passport_number','Номер загранпаспорта'),('passport_issued','Дата выдачи'),('passport_expires','Срок действия')]:
            if not p.get(key):issues.append('Не заполнено: '+label)
        if p.get('passport_type')!='0':issues.append('Для собственного документа нужен загранпаспорт, а не паспорт РФ.')
        if p.get('passport_number') and not re.fullmatch(r'[A-Za-z0-9 ]{5,30}',p['passport_number']):issues.append('Проверьте номер загранпаспорта.')
        if issued and (issued>timezone.localdate() or (birth and issued<birth)):issues.append('Некорректная дата выдачи паспорта.')
        if expiry and issued and expiry<=issued:issues.append('Срок действия паспорта раньше даты выдачи.')
        if expiry and departure and expiry<departure:issues.append('Паспорт истекает до окончания поездки.')
    if age is not None and age<18 and p.get('parent_tourist'):
        parent=linked(application.contract).filter(pk=p['parent_tourist']).first()
        if not parent or parent.pk==application.tourist_id or not parent.birthday or age_on(parent.birthday,arrival)<18:issues.append('Проверьте выбранного взрослого представителя ребёнка.')
    if age is not None and age<18 and not p.get('relationship'):issues.append('Для ребёнка укажите родственную связь/полномочия представителя.')
    if age is not None and age<18 and not p.get('parent_tourist') and not p.get('guardian_details'):issues.append('Укажите родителя либо сведения о законном представителе.')
    for key,label in [('travel_confirmed','Проверьте даты, рейс и название отеля'),('identity_confirmed','Сверьте данные с загранпаспортом'),
        ('previous_visas_confirmed','Подтвердите сведения о предыдущих визах'),('travel_history_confirmed','Подтвердите историю последних 14 дней'),
        ('portal_rules_checked','Проверьте актуальные вопросы и условия официального портала')]:
        if not p.get(key):issues.append(label+'.')
    answers=p.get('answers',[])
    if not answers:issues.append('Добавьте точные вопросы декларации и подтверждённые ответы, без предположений.')
    seen=set()
    for answer in answers:
        if not answer.get('question') or not answer.get('answer') or answer.get('confirmed') is not True:issues.append('Есть неполный или неподтверждённый ответ анкеты.')
        key=normalized(answer.get('question',''))
        if key in seen:issues.append('Вопрос анкеты повторяется; проверьте ответы.')
        seen.add(key)
    if bool(p.get('expected_fee'))!=bool(p.get('expected_fee_currency')) and p.get('expected_fee') not in ('0','0.00'):issues.append('Ожидаемый сбор и его валюту нужно указывать вместе.')
    if p.get('expected_fee') is not None and p.get('expected_fee')!='' and not re.fullmatch(r'[A-Z]{3}',p.get('expected_fee_currency','')):issues.append('Укажите валюту ожидаемого сбора (ISO из трёх букв).')
    snapshots=application.contract.lines.filter(tourist=application.tourist).values_list('tourist_snapshot',flat=True)
    if any(s and any(str(s.get(k,''))!=str(getattr(application.tourist,k) or '') for k in ('passport_number','surname','given_name') if s.get(k)) for s in snapshots) and not p.get('identity_confirmed'):
        issues.append('В договоре сохранён другой паспорт/ФИО туриста: проверьте актуальный документ.')
    return list(dict.fromkeys(issues))


def applicant_data(application):
    p=application.preparation
    age=age_on(date.fromisoformat(p['birthday']),date.fromisoformat(p['arrival_date']))
    own=True
    parent=ETAApplication.objects.filter(contract=application.contract,tourist_id=p.get('parent_tourist')).first() if p.get('parent_tourist') else None
    return {
      'person':{'surname':p['surname'].upper(),'given_names':p['given_names'].upper(),'gender':p['gender'],
        'birth_date':p['birthday'],'nationality':p['nationality'],'birth_country':p['birth_country'],
        'age_on_arrival':age,'occupation':'MANAGER' if age>=18 else p.get('child_occupation','')},
      'passport':{'own':own,'number':re.sub(r'\s','',p.get('passport_number','')).upper() if own else '',
        'issued_on':p.get('passport_issued','') if own else '', 'expires_on':p.get('passport_expires','') if own else ''},
      'home':{key:p['home_'+key] for key in ('address','city','region','country')},
      'contact':{'email':EMAIL,'email_confirmation':EMAIL,'phone':re.sub(r'[\s()\-]','',p['phone'])},
      'travel':{key:p[key] for key in ('arrival_date','departure_date','departure_airport','arrival_airport','airline','flight_number')},
      'accommodation':{'name':p['hotel_name'],'full_address':p.get('hotel_address','')},
      'confirmed_answers':{'declarations':p['answers'],'previous_visas':p['previous_visas'],
        'travel_last_14_days':p['travel_last_14_days'],'confirmed_by':p['confirmed_by'],'confirmed_at':p['confirmed_at']},
      'child':None if age>=18 else {'own_passport':own,'application_mode':'separate',
        'parent_tourist_id':p.get('parent_tourist'),'parent_application_id':str(parent.pk) if parent else None,
        'relationship':p['relationship'],'guardian_details':p.get('guardian_details','')},
    }


@transaction.atomic
@sensitive_variables()
def export_applications(contract,ids,actor):
    apps=list(ETAApplication.objects.select_for_update().filter(contract=contract,id__in=ids).select_related('tourist','contract').defer('approval_notice').order_by('tourist_id','pk'))
    if not apps or len(apps)!=len(set(ids)) or len(apps)>50:raise ValidationError('Выберите от 1 до 50 заданий этого договора.')
    batches={app.active_export_id for app in apps}
    if len(batches)==1 and None not in batches:
        batch=ETAExport.objects.get(pk=batches.pop())
        if {str(a.pk) for a in apps}!={a['application_id'] for a in batch.payload['applicants']}:raise ValidationError('Эти задания уже переданы. Скачайте исходный пакет по ссылке в списке.')
        return batch
    if any(app.active_export_id for app in apps):raise ValidationError('Часть заданий уже передана. Повторный запуск запрещён; скачайте исходный пакет.')
    entries=[];identity_keys=set()
    for app in apps:
        if not linked(contract).filter(pk=app.tourist_id).exists():raise ValidationError('Турист больше не связан с договором.')
        if app.source_hash!=source_hash(contract,app.tourist):raise ValidationError('Исходные данные изменились. Откройте подготовку и заново проверьте сведения.')
        issues=assess(app)
        if issues or app.status!='ready':raise ValidationError('Есть незаполненные/противоречивые сведения. Откройте подготовку каждого выбранного туриста.')
        data=applicant_data(app)
        identity=hmac.new(settings.SECRET_KEY.encode(),('eta-passport:'+identity_country(data['person']['nationality'])+':'+data['passport']['number']).encode(),hashlib.sha256).hexdigest()
        if identity in identity_keys:raise ValidationError('В выбранном пакете повторяется один и тот же паспорт. Выберите одну карточку туриста.')
        if ETAApplication.objects.filter(active_identity_key=identity).exclude(pk=app.pk).exists():raise ValidationError('Для этого паспорта уже есть переданное задание. Сначала проверьте результат предыдущего оформления.')
        identity_keys.add(identity);app.active_identity_key=identity
        entries.append({'application_id':str(app.pk),'tourist_id':app.tourist_id,'source_sha256':app.source_hash,
            'data_sha256':digest(data),'data':data,'expected_fee':app.preparation.get('expected_fee'),
            'expected_fee_currency':app.preparation.get('expected_fee_currency','')})
    batch=ETAExport.objects.create(contract=contract,created_by=actor)
    batch.payload={'schema':SCHEMA,'batch_id':str(batch.pk),'contract_id':contract.pk,'contract_exchange_id':str(contract.exchange_id),
        'created_at':timezone.now().isoformat(),'handoff_token':secrets.token_urlsafe(32),'official_portal':PORTAL,
        'date_format':'YYYY-MM-DD','portal_date_format':'MM-DD-YYYY','submission_authorized':False,
        'requirements':{'human_confirmation_required':True,'stop_on_captcha':True,'stop_on_unconfirmed_fields':True,
          'check_current_child_rules':True,'find_hotel_address_if_missing':True,'structure_home_address_from_payer':True,'check_actual_fee':True,'never_retry_uncertain_submission':True},'applicants':entries}
    batch.save(update_fields=['payload'])
    for app in apps:
        app.active_export=batch
        try:app.save(update_fields=['active_export','active_identity_key','updated_at'])
        except IntegrityError:raise ValidationError('Для этого паспорта уже создано другое активное задание. Повторный запуск остановлен.') from None
    AuditEvent.objects.create(actor=actor,object_type='crm.ETAExport',object_id=str(batch.pk),action='eta_exported',changes={'applications':[str(a.pk) for a in apps]})
    return batch


def review_issues(app,result=None):
    r=result if result is not None else app.result
    issues=[]
    summary=r.get('portal_summary')
    expected=next((entry['data'] for entry in app.active_export.payload['applicants'] if entry['application_id']==str(app.pk)),None) if app.active_export_id else None
    if expected is None:return ['Нет действующего пакета задания.']
    if not isinstance(summary,dict):return ['Нет фактической сводки портала.']
    for key in SUMMARY_GROUPS:
        if key=='home':
            actual=summary.get(key,{})
            if not isinstance(actual,dict) or set(actual)!=set(expected[key]) or any(not isinstance(actual.get(k),str) or not actual[k].strip()  for k in expected[key]):
                issues.append('Домашний адрес в сводке должен содержать адрес, город, регион и страну; перевод сверяется пользователем.')
            continue
        if key=='accommodation' and not expected[key]['full_address']:
            actual=summary.get(key,{})
            from urllib.parse import urlsplit
            source=r.get('hotel_address_source','')
            try:
                address_url=urlsplit(source) if isinstance(source,str) else None
                valid_source=bool(address_url and address_url.scheme in ('http','https') and address_url.hostname and not address_url.username and not address_url.password)
            except ValueError:valid_source=False
            if not isinstance(actual,dict) or actual.get('name')!=expected[key]['name'] or not isinstance(actual.get('full_address'),str) or not actual['full_address'].strip() or not valid_source:
                issues.append('Исполнитель должен найти полный адрес выбранного отеля и указать источник.')
            continue
        if key not in summary or canonical(summary[key])!=canonical(expected[key]):issues.append('Фактическая сводка отличается от подготовленных данных: '+key)
    answers={normalized(a['question']):normalized(a['answer']) for a in app.preparation.get('answers',[]) if a.get('confirmed')}
    additional=summary.get('additional_fields',{})
    if not isinstance(additional,dict):issues.append('Некорректный список дополнительных полей.')
    else:
        def answer_key(v):
            key=normalized(v)
            return 'yes' if key in ('yes','да','true','1') else 'no' if key in ('no','нет','false','0') else key
        for question,value in additional.items():
            if normalized(question) not in answers or answer_key(answers[normalized(question)])!=answer_key(value):issues.append('Неподтверждённое дополнительное поле портала: '+str(question)[:200])
    if set(summary)-set(SUMMARY_GROUPS)-{'additional_fields'}:issues.append('В сводке есть неизвестные обязательные поля; требуется сверка.')
    if r.get('unconfirmed_fields'):issues.append('Исполнитель обнаружил неподтверждённые значения (в том числе скрытые поля).')
    if r.get('captcha_required'):issues.append('Требуется участие пользователя: CAPTCHA.')
    if r.get('portal_rules_changed'):issues.append('Условия/обязательные вопросы портала изменились; требуется повторная проверка.')
    conditions=r.get('portal_conditions')
    if not isinstance(conditions,dict) or not isinstance(conditions.get('text'),str) or not conditions['text'].strip() or len(conditions['text'])>100000 or conditions.get('sha256')!=hashlib.sha256(conditions['text'].encode()).hexdigest():
        issues.append('Не получен проверяемый текст актуальных условий портала для согласования.')
    fee=r.get('fee')
    if not isinstance(fee,dict) or fee.get('amount') is None or not fee.get('currency'):issues.append('Фактический сбор ещё не установлен.')
    elif app.preparation.get('expected_fee') not in (None,''):
        if Decimal(str(fee['amount']))!=Decimal(app.preparation['expected_fee']) or fee['currency']!=app.preparation.get('expected_fee_currency'):issues.append('Неожиданный сбор. Подача остановлена до отдельного согласования.')
    return issues


def authorization_context(app):
    if app.authorization:return app.authorization
    return {'application_id':str(app.pk),'batch_id':str(app.active_export_id),'tourist_id':app.tourist_id,
        'authorized_at':app.submission_authorized_at.isoformat(),'review_sha256':digest(app.result.get('portal_summary')),
        'fee':str(app.actual_fee),'currency':app.fee_currency,'conditions_sha256':app.result['portal_conditions']['sha256']}


def authorization_payload(app):
    if not app.submission_authorized_at:raise ValidationError('Подача ещё не подтверждена.')
    return {'schema':'aborigen.sri-lanka-eta.authorization.v1',**authorization_context(app),
        'authorization_token':signing.dumps(authorization_context(app),salt='eta-submit')}


def validate_pdf(notice):
    if not isinstance(notice,dict) or notice.get('mime_type')!='application/pdf':raise ValidationError('Approval Notice принимается только как PDF.')
    content=notice.get('content_base64','')
    if not isinstance(content,str) or len(content)>7*1024*1024:raise ValidationError('Approval Notice слишком большой.')
    try:body=base64.b64decode(content,validate=True)
    except (ValueError,TypeError):raise ValidationError('Некорректный base64 Approval Notice.') from None
    if not body.startswith(b'%PDF-') or len(body)>5*1024*1024:raise ValidationError('Некорректный PDF Approval Notice.')
    checksum=hashlib.sha256(body).hexdigest()
    if notice.get('sha256')!=checksum:raise ValidationError('Не совпала контрольная сумма PDF.')
    return body,checksum


@transaction.atomic
@sensitive_variables()
def import_results(contract,payload,actor):
    if not isinstance(payload,dict) or payload.get('schema')!=RESULT_SCHEMA:raise ValidationError('Неизвестный формат результата ETA.')
    try:batch=ETAExport.objects.select_for_update().get(pk=payload.get('batch_id'),contract=contract)
    except (ETAExport.DoesNotExist,ValueError,TypeError,ValidationError):raise ValidationError('Пакет результата не принадлежит этому договору.') from None
    if type(payload.get('contract_id')) is not int or payload.get('contract_id')!=contract.pk or payload.get('contract_exchange_id')!=str(contract.exchange_id):raise ValidationError('Идентификаторы договора в результате не совпали.')
    token=payload.get('handoff_token')
    if not isinstance(token,str) or not secrets.compare_digest(token.encode('utf-8'),batch.payload['handoff_token'].encode('utf-8')):raise ValidationError('Не совпал ключ передачи пакета.')
    results=payload.get('results')
    if not isinstance(results,list) or not 1<=len(results)<=50:raise ValidationError('В результате должно быть от 1 до 50 туристов.')
    receipt=digest(payload)
    if receipt in batch.receipt_hashes:return 0
    entries={row['application_id']:row for row in batch.payload['applicants']}
    seen=set();changed=0
    for r in results:
        if not isinstance(r,dict):raise ValidationError('Некорректная запись результата.')
        allowed={'application_id','tourist_id','data_sha256','stage','updated_at','application_number','portal_status','fee','stop_reason',
            'portal_summary','hotel_address_source','unconfirmed_fields','captcha_required','portal_rules_changed','submission_uncertain',
            'portal_conditions','authorization_token','approval_confirmed','approval_notice'}
        if set(r)-allowed:raise ValidationError('В результате есть неизвестные поля протокола v1. HTML/отладочные дампы не принимаются.')
        key=r.get('application_id')
        if not isinstance(key,str) or key not in entries or key in seen:raise ValidationError('Задание отсутствует в пакете либо повторяется.')
        seen.add(key);entry=entries[key]
        try:app=ETAApplication.objects.select_for_update().select_related('tourist','contract').get(pk=key,contract=contract,active_export=batch)
        except ETAApplication.DoesNotExist:raise ValidationError('Задание больше не относится к этой передаче.') from None
        if type(r.get('tourist_id')) is not int or r.get('tourist_id')!=app.tourist_id or r.get('data_sha256')!=entry['data_sha256']:raise ValidationError('Результат относится к другому туристу или другой версии данных.')
        if 'submission_uncertain' in r and type(r['submission_uncertain']) is not bool:raise ValidationError('Некорректный признак неопределённого результата отправки.')
        stage=r.get('stage')
        if stage not in TRANSITIONS.get(app.status,set()):raise ValidationError('Недопустимый переход этапа ETA.')
        if stage in SENT|{'awaiting_confirmation'}:
            if any(type(r.get(key)) is not bool for key in ('captcha_required','portal_rules_changed')) or not isinstance(r.get('unconfirmed_fields'),list) or len(r['unconfirmed_fields'])>100 or any(not isinstance(value,str) or len(value)>500 for value in r['unconfirmed_fields']):
                raise ValidationError('Нужен явный отчёт о CAPTCHA, изменении условий и неподтверждённых полях.')
        try:updated=parse_datetime(r.get('updated_at','')) if isinstance(r.get('updated_at'),str) else None
        except ValueError:updated=None
        if not updated or timezone.is_naive(updated) or updated>timezone.now()+timedelta(minutes=5):raise ValidationError('Нужно корректное время обновления с часовым поясом.')
        safe={k:v for k,v in r.items() if k not in ('approval_notice','authorization_token')}
        if app.portal_updated_at and updated<=app.portal_updated_at:
            if updated==app.portal_updated_at and safe==app.result and not r.get('approval_notice'):continue
            raise ValidationError('Получен устаревший либо противоречивый результат.')
        number=r.get('application_number','');portal_status=r.get('portal_status','');reason=r.get('stop_reason','')
        if any(not isinstance(v,str) for v in (number,portal_status,reason)) or len(number)>100 or len(portal_status)>250 or len(reason)>3000:raise ValidationError('Некорректные номер, статус или причина остановки.')
        if app.application_number and number and number!=app.application_number:raise ValidationError('Номер ETA уже сохранён и отличается. Новый номер автоматически не подменяется.')
        fee=r.get('fee')
        amount=None;currency=''
        if fee is not None:
            if not isinstance(fee,dict):raise ValidationError('Некорректный сбор.')
            currency=fee.get('currency','')
            try:amount=Decimal(str(fee.get('amount')))
            except (InvalidOperation,ValueError):raise ValidationError('Некорректная сумма сбора.') from None
            if not amount.is_finite() or amount<0 or amount>Decimal('9999999999.99') or amount!=amount.quantize(Decimal('.01')) or not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency):raise ValidationError('Некорректные сбор или валюта.')
        if stage in SENT-{'referral'}:
            if not app.submission_authorized_at:raise ValidationError('В CRM нет подтверждения окончательной подачи для этого туриста.')
            try:authorization=signing.loads(r.get('authorization_token',''),salt='eta-submit')
            except (signing.BadSignature,TypeError):raise ValidationError('Не подтверждено разрешение на подачу.') from None
            if authorization!=authorization_context(app):raise ValidationError('Разрешение относится к другой версии сводки.')
            if stage=='submitted' and (not isinstance(r.get('portal_summary'),dict) or digest(r['portal_summary'])!=authorization['review_sha256']):
                raise ValidationError('При подаче использована другая сводка, чем подтвердил пользователь.')
            if stage=='submitted':
                conditions=r.get('portal_conditions')
                if not isinstance(conditions,dict) or not isinstance(conditions.get('text'),str) or hashlib.sha256(conditions['text'].encode()).hexdigest()!=authorization['conditions_sha256']:
                    raise ValidationError('Условия портала изменились после подтверждения.')
            if r.get('unconfirmed_fields') or r.get('captcha_required') or r.get('portal_rules_changed'):
                raise ValidationError('Есть неподтверждённые поля, CAPTCHA или изменившиеся условия. Подача не подтверждена.')
            if amount!=app.actual_fee or currency!=app.fee_currency:raise ValidationError('Сбор изменился после подтверждения. Требуется остановка и повторная проверка.')
            if not (number or app.application_number) or not portal_status:raise ValidationError('Для поданного заявления нужны номер и исходный статус портала.')
        if stage=='referral' and not portal_status:raise ValidationError('Для направления в иммиграционную службу нужен исходный статус портала.')
        if stage=='approved' and r.get('approval_confirmed') is not True:raise ValidationError('Подтверждение получения не является одобрением ETA. Нужен подтверждённый статус одобрения.')
        if stage in ('error','needs_data','referral') and not reason:raise ValidationError('Укажите причину остановки/ошибки.')
        if r.get('portal_summary') is not None and not isinstance(r['portal_summary'],dict):raise ValidationError('Фактическая сводка должна быть объектом JSON.')
        if r.get('approval_notice') is not None:
            if stage!='approved':raise ValidationError('Approval Notice относится только к подтверждённому одобрению.')
            notice=r['approval_notice']
            if not isinstance(notice,dict):raise ValidationError('Некорректное описание Approval Notice.')
            if notice.get('application_id')!=str(app.pk) or type(notice.get('tourist_id')) is not int or notice['tourist_id']!=app.tourist_id or notice.get('application_number')!=(number or app.application_number):
                raise ValidationError('Approval Notice не привязан к нужному туристу и номеру ETA.')
            body,checksum=validate_pdf(notice)
            if ETAApplication.objects.filter(approval_sha256=checksum).exclude(pk=app.pk).exists():raise ValidationError('Этот PDF уже привязан к другому туристу. Проверьте файл одобрения.')
            app.approval_notice=body;app.approval_sha256=checksum
        if stage=='awaiting_confirmation':
            app.submission_authorized_at=None;app.submission_authorized_by=None;app.authorization={}
        app.status=stage;app.result=safe;app.portal_updated_at=updated
        if stage=='approved':app.active_identity_key=None
        app.application_number=number or app.application_number;app.portal_status=portal_status
        app.actual_fee=amount if fee is not None else app.actual_fee;app.fee_currency=currency if fee is not None else app.fee_currency;app.stop_reason=reason;app.save()
        AuditEvent.objects.create(actor=actor,object_type='crm.ETAApplication',object_id=str(app.pk),action='eta_result_imported',changes={'stage':stage,'has_approval':bool(app.approval_sha256)})
        changed+=1
    batch.receipt_hashes=(batch.receipt_hashes+[receipt])[-1000:];batch.save(update_fields=['receipt_hashes'])
    return changed
