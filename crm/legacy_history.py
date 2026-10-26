"""History migration: explicit source keys, raw archive and atomic training import."""
import datetime
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import transaction
from . import models as m
from .legacy_library import LibraryImportError

class HistoryImportError(ValueError):pass

KEYS={'PRIZNAK_DOCUMENTS':'ID_PRIZNAK_DOCUMENT','COMPANY':'ID_COMPANY','LIST_DOCUMENTS':'ID_DOC','LIST_MANYS':'ID_MANY','LIST_CONTACT_COMPANY':'ID_CONTACT','LIST_TOVAR_DOC':'ID_TOVAR_DOC','LIST_TELEPHONES':'ID_TELPHONE','LIST_EMAIL_CLIENT':'id_email','LIST_REQUIS_FIZ':'ID_LIST_REQUIS_FIZ','LIST_REQUIS_COMPANY':'ID_REQUIS','TIP_DOCUMENTS':'ID_TIP_DOCUMENT','VID_CONTACT':'ID_VID_CONTACT','VID_COMPANY':'ID_VID_COMPANY','LIST_VALUTA':'id_valuta','LIST_SPR_SCHETS_MONY':'ID_LIST_SPR_LIST_SCHETS_MONY','MANAGERS':'ID_MANAGER',**{t:'id' for t in ['ADD_SPR_OPEROTOR','ADD_SPR_PITANIE','ADD_SPR_TRANSFER','ADD_SPR_STRAHOVKA','ADD_SPR_country','ADD_SPR_city_fly']}}
MAX_PACKAGE=8*1024*1024
MAX_EXPANDED=100*1024*1024


def load_history(stream):
    blob=stream.read(MAX_PACKAGE+1)
    if len(blob)>MAX_PACKAGE:raise HistoryImportError('Пакет должен быть не больше 8 МБ.')
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            if len(archive.infolist())!=1 or archive.namelist()!=['history.json'] or archive.getinfo('history.json').file_size>MAX_EXPANDED:raise HistoryImportError('Некорректный архив истории.')
            raw=archive.read('history.json')
        data=json.loads(raw.decode('utf-8'))
        if not isinstance(data,dict) or data.get('format') not in ('aborigen-legacy-history-v1','aborigen-legacy-history-v2'):raise HistoryImportError('Неизвестный формат истории.')
        source=data.get('source_key');tables=data.get('tables')
        import re
        if not isinstance(source,str) or not re.fullmatch('[a-zA-Z0-9:_-]{1,100}',source):raise HistoryImportError('Некорректный источник.')
        if not isinstance(data.get('snapshot'),str) or len(data['snapshot'])>64:raise HistoryImportError('Некорректная дата снимка.')
        if isinstance(tables,dict) and data['format']=='aborigen-legacy-history-v1':tables.setdefault('PRIZNAK_DOCUMENTS',[])
        if not isinstance(tables,dict) or set(tables)!=set(KEYS):raise HistoryImportError('Неверный набор таблиц.')
        if sum(len(rows) if isinstance(rows,list) else 200001 for rows in tables.values())>150000:raise HistoryImportError('Слишком много записей.')
        indexes={}
        for table,rows in tables.items():
            index={}
            for row in rows:
                if not isinstance(row,dict) or len(row)>150:raise HistoryImportError('Некорректная запись: '+table)
                key=row.get(KEYS[table])
                if type(key) is not int or not 0<key<=2147483647 or key in index:raise HistoryImportError('Повторяющийся или неверный ключ: '+table)
                if any(not isinstance(k,str) or not isinstance(v,(str,int,float,bool,type(None))) for k,v in row.items()):raise HistoryImportError('Недопустимый тип поля: '+table)
                for value in row.values():
                    if isinstance(value,str) and (len(value)>1024*1024 or any(0xd800<=ord(c)<=0xdfff for c in value)):raise HistoryImportError('Некорректный текст: '+table)
                index[key]=row
            indexes[table]=index
        # The employee table is intentionally an allowlist, never legacy credentials.
        if any(set(r)-{'ID_MANAGER','MANAGER_NAME'} for r in tables['MANAGERS']):raise HistoryImportError('Таблица сотрудников содержит лишние поля.')
        data['indexes']=indexes;data['digest']=hashlib.sha256(raw).hexdigest()
        validate_links(data)
        return data
    except HistoryImportError:raise
    except (zipfile.BadZipFile,KeyError,TypeError,ValueError,UnicodeError,OSError,RuntimeError,OverflowError,RecursionError) as error:raise HistoryImportError('Пакет истории повреждён.') from error


def validate_links(data):
    indexes=data['indexes'];customers=indexes['COMPANY'];docs=indexes['LIST_DOCUMENTS'];needed=set()
    for table in ('LIST_DOCUMENTS','LIST_MANYS','LIST_CONTACT_COMPANY'):
        for row in indexes[table].values():
            if row.get('TRASH') not in (None,0):raise HistoryImportError('В рабочие записи попала корзина: '+table)
            if row.get('ID_COMPANY') not in customers:raise HistoryImportError('Не найден заказчик: '+table)
            needed.add(row['ID_COMPANY'])
    if any(r.get('TRASH') not in (None,0) and r['ID_COMPANY'] not in needed for r in customers.values()):raise HistoryImportError('В пакете есть ненужные удалённые заказчики.')
    if any(r.get('ID_TIP_DOC') in (19,24) for r in docs.values()):raise HistoryImportError('СЧЕТ и ПКО не входят в перенос.')
    if any(r.get('ID_DOC') not in docs for r in indexes['LIST_TOVAR_DOC'].values()):raise HistoryImportError('Строка не связана с переносимым договором.')
    for table in ('LIST_TELEPHONES','LIST_EMAIL_CLIENT','LIST_REQUIS_FIZ','LIST_REQUIS_COMPANY'):
        if any(r.get('ID_COMPANY') not in customers for r in indexes[table].values()):raise HistoryImportError('Реквизиты не связаны с заказчиком: '+table)
    if any(r.get('ID_PRIZNAK_CONTACT') not in (1,2) for r in indexes['LIST_CONTACT_COMPANY'].values()):raise HistoryImportError('Неизвестный статус задачи.')
    if any(r.get('ID_SUB_PRIZNAK_MANY')!=1 or r.get('ID_NAPR')!=1 for r in indexes['LIST_MANYS'].values()):raise HistoryImportError('Неизвестный статус или направление платежа.')


def string(value):return str(value).replace('\x00','').strip() if value is not None else ''

def money(value):
    try:
        result=Decimal(str(value if value is not None else 0)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        if not result.is_finite() or abs(result)>=Decimal('1000000000000'):raise InvalidOperation
        return result
    except (InvalidOperation,ValueError):raise HistoryImportError('Недопустимая денежная сумма.')


def date(value):
    if not value:return None
    try:result=datetime.date.fromisoformat(str(value)[:10])
    except ValueError:raise HistoryImportError('Некорректная дата в источнике.')
    return result if result.year>=1900 else None


def plain(value):
    value=string(value)
    if value.startswith('{\\rtf'):
        from striprtf.striprtf import rtf_to_text
        try:value=rtf_to_text(value,encoding='cp1251',errors='replace')
        except (ValueError,IndexError,OverflowError):return ''
    return value.encode('utf-16-le',errors='surrogatepass').decode('utf-16-le',errors='replace')


def prepare_history(data):
    """Validate/prepare all target field values without database writes."""
    from .legacy_rules import country,departure,nights
    i=data['indexes'];issues=[];targets={k:[] for k in ('customers','contracts','lines','payments','tasks')}
    def issue(kind,table,key,**details):issues.append({'kind':kind,'table':table,'source_id':key,**details})
    def build(model,values,table,key):
        for field,value in list(values.items()):
            f=model._meta.get_field(field)
            if isinstance(f,m.models.CharField) and len(value)>f.max_length:
                issue('text_shortened_original_retained',table,key,field=field);values[field]=value[:f.max_length]
        return model(**values)
    phones=defaultdict(list);emails=defaultdict(list);requisites=defaultdict(list);legal=defaultdict(list)
    for row in i['LIST_TELEPHONES'].values():
        value=string(row.get('TELEPHONE'))
        if value and value not in phones[row['ID_COMPANY']]:phones[row['ID_COMPANY']].append(value)
    for row in i['LIST_EMAIL_CLIENT'].values():
        value=string(row.get('email'))
        if value and value not in emails[row['ID_COMPANY']]:emails[row['ID_COMPANY']].append(value)
    for row in i['LIST_REQUIS_FIZ'].values():requisites[row['ID_COMPANY']].append(row)
    for row in i['LIST_REQUIS_COMPANY'].values():legal[row['ID_COMPANY']].append(row)
    for key,row in i['COMPANY'].items():
        ps=phones[key];es=emails[key];kind='company' if row.get('YUR_FIZ')==1 else 'person'
        # Main card is authoritative; document-specific historical requisites remain snapshots.
        values={'kind':kind,'name':string(row.get('COMPANY_NAME')) or f'Заказчик старой CRM №{key}','company_name':string(row.get('COMPANY_NAME')) if kind=='company' else '', 'surname':string(row.get('FAM_FIZ')),'given_name':string(row.get('NAME_FIZ')),'patronymic':string(row.get('OTCH_FIZ')),'main_phone':ps[0] if ps else '', 'phones':'\n'.join(ps[1:]),'main_email':es[0] if es else '', 'emails':'\n'.join(es[1:]),'address':string(row.get('ADRES')),'birthday':date(row.get('DR_COMPANY')),'passport_number':' '.join(filter(None,[string(row.get('PASPORT_LOCAL_SER')),string(row.get('PASPORT_LOCAL_NUMBER'))])),'passport_issued':date(row.get('PASPORT_LOCAL_DATE')),'passport_issued_by':string(row.get('PASPORT_LOCAL_KEM')),'passport_code':string(row.get('PASPORT_LOCAL_NUMB_PODRAZDEL')),'passport':plain(row.get('DOP_INF')),'inn':string(row.get('INN'))}
        if kind=='person':values['name']=' '.join(filter(None,[values['surname'],values['given_name'],values['patronymic']])) or values['name']
        personal=sorted(requisites[key],key=lambda r:(r.get('USE_DEFAULT')=='1',r['ID_LIST_REQUIS_FIZ']),reverse=True)
        if kind=='person' and personal:
            req=personal[0]
            for target,source_field in {'passport_number':'PASPORT_NUMBER','passport_issued_by':'PASPORT_VIDAN_KEM','passport_code':'KOD_PODRAZDELEN_FIZ','address':'ADDRES_PROPIS','main_phone':'KONT_TEL','main_email':'EMAIL_FIZ'}.items():
                values[target]=values[target] or string(req.get(source_field))
            values['passport_number']=values['passport_number'] or ' '.join(filter(None,[string(req.get('Seria_pasp_FIZ')),string(req.get('N_PASP_FIZ'))]))
            values['passport_issued']=values['passport_issued'] or date(req.get('PASPORT_VIDAN_DATA'))
            values['birthday']=values['birthday'] or date(req.get('DATE_HAPY'))
        rs=sorted(legal[key],key=lambda r:(r.get('USE_DEFAULT')=='1',r['ID_REQUIS']),reverse=True)
        if kind=='company' and rs:
            req=rs[0]
            for target,source in {'legal_address':'ADRES_YUR','bank_name':'BANK_NAME','bik':'BIK','account':'RS','correspondent_account':'KS','kpp':'KPP','ogrn':'OGRN_CLIENT','representative':'DIR_NAME','representative_basis':'DEYSTV_CLIENT'}.items():values[target]=string(req.get(source))
            values['inn']=values['inn'] or string(req.get('INN'))
        if row.get('TRASH'):issue('necessary_deleted_customer_restored','COMPANY',key)
        targets['customers'].append((key,build(m.Customer,values,'COMPANY',key)))
    line_totals=defaultdict(lambda:Decimal('0'));counts=defaultdict(lambda:[0,0])
    for key,row in i['LIST_TOVAR_DOC'].items():
        name=' '.join(filter(None,[string(row.get('ADD_LAST_NAME')),string(row.get('ADD_FIRST_NAME')),string(row.get('ADD_otchestvo'))]))
        snapshot={label:string(row.get(field)) for label,field in [('Фамилия','ADD_LAST_NAME'),('Имя','ADD_FIRST_NAME'),('Отчество','ADD_otchestvo'),('Пол','ADD_POL'),('Серия паспорта','ADD_PASPORT_SERIYA'),('Номер паспорта','ADD_NOMER_1'),('Кем выдан','ADD_PASPORT_VYDAN_1')] if string(row.get(field))}
        for label,field in [('Дата рождения','ADD_DATE_ROZDENIYA'),('Дата выдачи','ADD_PASPORT_VYDAN_DATE'),('Действителен до','ADD_PASPORT_SROK_DATE')]:
            value=date(row.get(field))
            if value:snapshot[label]=value.isoformat()
        values={'description':string(row.get('TOVAR_DOC')) or name or 'Строка старого договора','tourist_snapshot':snapshot,'amount':money(row.get('SUMMA'))}
        line_totals[row['ID_DOC']]+=values['amount']
        birth=date(row.get('ADD_DATE_ROZDENIYA'));start=date(i['LIST_DOCUMENTS'][row['ID_DOC']].get('ADD_DATE_BIG'))
        if name and birth and start and birth<=start:
            age=start.year-birth.year-((start.month,start.day)<(birth.month,birth.day));counts[row['ID_DOC']][int(age<18)]+=1
        targets['lines'].append((key,build(m.ContractLine,values,'LIST_TOVAR_DOC',key)))
    for key,row in i['LIST_DOCUMENTS'].items():
        day=date(row.get('DATA_DOC'))
        if not day:raise HistoryImportError(f'Не указана дата договора: {key}')
        req=i['LIST_REQUIS_FIZ'].get(row.get('ID_LIST_REQUIS_FIZ'));corp=i['LIST_REQUIS_COMPANY'].get(row.get('ID_REQUIS_COMPANY'))
        if req and req['ID_COMPANY']!=row['ID_COMPANY']:issue('snapshot_customer_differs','LIST_DOCUMENTS',key)
        summary=money(row.get('SUMMA'));adjustment=money(summary-line_totals[key])
        if adjustment:issue('header_lines_difference','LIST_DOCUMENTS',key,header=str(summary),lines=str(line_totals[key]),difference=str(adjustment))
        services='\n'.join(label+': '+string(row[field]) for field,label in [('ADD_PROEZD','Проезд'),('ADD_VIZA','Виза'),('ADD_STRAHOVKA_NEVYEZD','Страховка от невыезда'),('ADD_EXURSII','Экскурсии'),('ADD_DOP_USLUGI','Дополнительные услуги'),('ADD_END_PUTESHESTVIYA','Конец путешествия'),('ADD_MARSHRUT','Маршрут')] if row.get(field))
        values={'number':string(row.get('NUMBER_DOC')),'date':day,'country':country(string(row.get('ADD_DOC_COUNTRY'))),'departure':departure(string(row.get('ADD_BIG_PUTESHESTVIYA'))),'region':string(row.get('ADD_MESTO_PUTESHESTVIYA')),'nights':nights(string(row.get('ADD_PRODOLZHITELNOCT'))),'start':date(row.get('ADD_DATE_BIG')),'end':date(row.get('ADD_DATE_END')),'hotel':string(row.get('ADD_HOTEL')),'room':string(row.get('ADD_NOMER')),'meal':string(row.get('ADD_PITANIE')),'transfer':string(row.get('ADD_TRANSFER')),'insurance':string(row.get('ADD_STRAHOVKA')),'services':services,'notes':plain(row.get('PRIM_DOC')),'operator_paid':date(row.get('ADD_DATE_OPLATY_TO')),'opening_operator_paid':money(row.get('ADD_SUM_OPLATY_TO')),'legacy_amount_adjustment':adjustment,'legacy_customer_snapshot':{'person':req or {},'company':corp or {}},'adults':counts[key][0],'children':counts[key][1]}
        if values['start'] and values['end'] and values['end']<values['start']:issue('source_dates_reversed','LIST_DOCUMENTS',key)
        targets['contracts'].append((key,build(m.Contract,values,'LIST_DOCUMENTS',key)))
    for key,row in i['LIST_MANYS'].items():
        amount=money(row.get('SUM_RUB'))
        if not amount:issue('zero_payment_archived','LIST_MANYS',key);continue
        if row.get('ID_DOC') not in i['LIST_DOCUMENTS']:issue('unallocated_payment_deferred','LIST_MANYS',key,amount=str(amount));continue
        if row['ID_COMPANY']!=i['LIST_DOCUMENTS'][row['ID_DOC']]['ID_COMPANY']:issue('payment_customer_differs','LIST_MANYS',key)
        day=date(row.get('DATE_MANY'))
        if not day:raise HistoryImportError(f'Не указана дата платежа: {key}')
        if row.get('ID_LIST_SPR_LIST_SCHETS_MONY') not in i['LIST_SPR_SCHETS_MONY']:issue('missing_payment_method_name','LIST_MANYS',key,method_source_id=row.get('ID_LIST_SPR_LIST_SCHETS_MONY'))
        values={'date':day,'kind':'customer_refund' if amount<0 else 'customer','amount':abs(amount),'notes':plain(row.get('DOP_PRIM')),'currency':''}
        targets['payments'].append((key,build(m.Payment,values,'LIST_MANYS',key)))
    for key,row in i['LIST_CONTACT_COMPANY'].items():
        day=date(row.get('DATA_CONTACT'))
        if not day:raise HistoryImportError(f'Не указана дата задачи: {key}')
        title=string(i['VID_CONTACT'].get(row.get('ID_VID_CONTACT'),{}).get('DISCRIPTION_VID_CONTCT')) or 'Задача старой CRM'
        description=plain(row.get('PRIMECHANIE'))
        values={'title':title,'description':description,'result':plain(row.get('REZULTAT_CONTACT')),'due':day,'done':row['ID_PRIZNAK_CONTACT']==2}
        targets['tasks'].append((key,build(m.Task,values,'LIST_CONTACT_COMPANY',key)))
    from collections import Counter
    report={'issue_counts':dict(Counter(v['kind'] for v in issues)),'counts':{kind:len(rows) for kind,rows in targets.items()},'restored_customers':sum(bool(r.get('TRASH')) for r in i['COMPANY'].values()),'issues':len(issues),'deferred_payments':[v['source_id'] for v in issues if v['kind']=='unallocated_payment_deferred'],'zero_payments':sum(v['kind']=='zero_payment_archived' for v in issues),'totals':{'contracts':str(sum((v.legacy_amount_adjustment+line_totals[key] for key,v in targets['contracts']),Decimal('0'))),'lines':str(sum(line_totals.values(),Decimal('0'))),'operator_paid':str(sum((v.opening_operator_paid for _,v in targets['contracts']),Decimal('0'))),'customer_net':str(sum((v.amount*(-1 if v.kind=='customer_refund' else 1) for _,v in targets['payments']),Decimal('0')))}}
    return targets,issues,report


@transaction.atomic
def apply_history(data,actor=None,progress=lambda message:None):
    from .legacy_rules import PAYMENT_NAMES,DOCUMENT_METHODS,country,departure
    source=data['source_key']
    previous=m.LegacyImportRun.objects.filter(source_key=source,section='history').first()
    if previous:
        if previous.content_sha256!=data['digest']:raise HistoryImportError('Из этого источника уже загружен другой снимок. Нужна отдельная сверка.')
        # Refuse a repeat when imported targets were deleted; never silently resurrect edits.
        grouped=defaultdict(list)
        for label,pk in previous.records.exclude(target_model='').values_list('target_model','target_id'):grouped[label].append(pk)
        if any(apps.get_model(label).objects.filter(pk__in=ids).count()!=len(set(ids)) for label,ids in grouped.items()):raise HistoryImportError('Ранее загруженные записи удалены. Повторная загрузка остановлена.')
        return previous,False
    if m.LegacyRecord.objects.filter(source_key=source).exists():raise HistoryImportError('В источнике уже есть частично сопоставленные записи.')
    targets,issues,report=prepare_history(data);i=data['indexes']
    run=m.LegacyImportRun.objects.create(source_key=source,section='history',content_sha256=data['digest'],source_snapshot=data['snapshot'],actor=actor)
    bindings={};reference_cache={}
    def bind(table,key,obj):bindings[(table,key)]=(obj._meta.label,obj.pk)
    def reference(model,name):
        name=string(name) or 'Не указан в старой CRM';max_length=model._meta.get_field('name').max_length
        if len(name)>max_length:raise HistoryImportError('Слишком длинное название справочника: '+model.__name__)
        cache=reference_cache.setdefault(model,{m.normalize_location(o.name):o for o in model.objects.all()})
        normalized=m.normalize_location(name)
        if normalized not in cache:cache[normalized]=model.objects.create(name=name)
        return cache[normalized]
    for table,model in [('ADD_SPR_OPEROTOR',m.Operator),('ADD_SPR_PITANIE',m.Meal),('ADD_SPR_TRANSFER',m.Transfer),('ADD_SPR_STRAHOVKA',m.Insurance),('TIP_DOCUMENTS',m.ContractType),('VID_CONTACT',m.TaskType),('LIST_SPR_SCHETS_MONY',m.PaymentMethod)]:
        field={'TIP_DOCUMENTS':'TIP_DOCUMENT','VID_CONTACT':'DISCRIPTION_VID_CONTCT','LIST_SPR_SCHETS_MONY':'NAME_SCHET'}.get(table,'name')
        for key,row in i[table].items():
            if table=='TIP_DOCUMENTS' and key in (19,24):continue
            if string(row.get(field)):
                name=PAYMENT_NAMES.get(key,'Другое') if table=='LIST_SPR_SCHETS_MONY' else row[field]
                bind(table,key,reference(model,name))
    for table,model in [('ADD_SPR_country',m.Country),('ADD_SPR_city_fly',m.DepartureCity)]:
        cache={m.normalize_location(o.name):o for o in model.objects.all()}
        for key,row in i[table].items():
            name=string(row.get('name'))
            name=country(name) if table=='ADD_SPR_country' else departure(name)
            if not name:continue
            normalized=m.normalize_location(name)
            if normalized not in cache:
                if len(name)>100:raise HistoryImportError('Слишком длинное название географического справочника.')
                code='legacy-'+hashlib.sha256(source.encode()).hexdigest()[:8]+'-'+str(key)
                cache[normalized]=model.objects.create(code=code,name=name,details={'legacy_source':source,'legacy_id':key})
            bind(table,key,cache[normalized])
    for name in {*PAYMENT_NAMES.values(),*DOCUMENT_METHODS.values(),'Другое'}:reference(m.PaymentMethod,name)
    progress('Заказчики и реквизиты')
    m.Customer.objects.bulk_create([o for _,o in targets['customers']],batch_size=100)
    customers=dict(targets['customers'])
    for key,obj in targets['customers']:bind('COMPANY',key,obj)
    contracts=dict(targets['contracts'])
    for key,obj in targets['contracts']:
        raw=i['LIST_DOCUMENTS'][key];obj.customer=customers[raw['ID_COMPANY']];obj.operator=reference(m.Operator,raw.get('ADD_OPERATOR'))
        obj.contract_type=reference(m.ContractType,i['TIP_DOCUMENTS'].get(raw.get('ID_TIP_DOC'),{}).get('TIP_DOCUMENT'))
        status_name=i['PRIZNAK_DOCUMENTS'].get(raw.get('ID_PRIZNZK_DOC'),{}).get('PRIZNAK_DOCUMENT','')
        method_name=DOCUMENT_METHODS.get(m.normalize_location(status_name))
        if method_name:obj.payment_method=reference(m.PaymentMethod,method_name)
    m.Contract.objects.bulk_create(list(contracts.values()),batch_size=100)
    for key,obj in targets['contracts']:bind('LIST_DOCUMENTS',key,obj)
    progress('Строки туристов и стоимость')
    from .legacy_tourists import attach_tourists
    attach_tourists(targets['lines'],i['LIST_TOVAR_DOC'],report)
    for key,obj in targets['lines']:obj.contract=contracts[i['LIST_TOVAR_DOC'][key]['ID_DOC']]
    m.ContractLine.objects.bulk_create([o for _,o in targets['lines']],batch_size=100)
    for key,obj in targets['lines']:bind('LIST_TOVAR_DOC',key,obj)
    progress('Клиентские платежи')
    for key,obj in targets['payments']:
        raw=i['LIST_MANYS'][key];obj.contract=contracts[raw['ID_DOC']];obj.legacy_payer=customers[raw['ID_COMPANY']]
        obj.method=reference(m.PaymentMethod,PAYMENT_NAMES.get(raw.get('ID_LIST_SPR_LIST_SCHETS_MONY'),'Другое'))
    m.Payment.objects.bulk_create([o for _,o in targets['payments']],batch_size=100)
    for key,obj in targets['payments']:bind('LIST_MANYS',key,obj)
    progress('Перенесённая оплата ТО')
    opening=[]
    for key,obj in targets['contracts']:
        amount=obj.opening_operator_paid
        if amount:
            payment=m.Payment(contract=obj,kind='operator' if amount>0 else 'operator_refund',amount=abs(amount),date=obj.operator_paid or obj.date,method=reference(m.PaymentMethod,'Тинькофф р/с'),currency='RUB',notes='Перенесённая суммарная оплата ТО из старой CRM; отдельная история платежей в источнике отсутствует.')
            opening.append((key,payment));obj.opening_operator_paid=Decimal('0')
    m.Payment.objects.bulk_create([o for _,o in opening],batch_size=100)
    m.Contract.objects.bulk_update([o for _,o in targets['contracts']],['opening_operator_paid'],batch_size=100)
    report['counts']['operator_payments']=len(opening)
    for key,obj in opening:bind('@operator_opening',key,obj)
    progress('Задачи')
    employees={};User=get_user_model();prefix='legacy_'+hashlib.sha256(source.encode()).hexdigest()[:10]+'_'
    for key,row in i['MANAGERS'].items():
        username=prefix+str(key)
        user=User.objects.filter(username=username).first()
        if user and (user.is_active or user.is_staff or user.is_superuser or user.has_usable_password()):raise HistoryImportError('Имя исторического сотрудника уже занято действующей учётной записью.')
        if user is None:user=User(username=username,is_active=False,is_staff=False,is_superuser=False)
        user.first_name=string(row.get('MANAGER_NAME'))[:150];user.set_unusable_password();user.save();employees[key]=user;bind('MANAGERS',key,user)
    latest={}
    for key,obj in targets['contracts']:
        raw=i['LIST_DOCUMENTS'][key];customer_id=raw['ID_COMPANY'];order=(string(raw.get('DATA_DOC')),key)
        if customer_id not in latest or order>latest[customer_id][0]:latest[customer_id]=(order,obj)
    linked_tasks=0
    for key,obj in targets['tasks']:
        raw=i['LIST_CONTACT_COMPANY'][key];obj.customer=customers[raw['ID_COMPANY']];obj.task_type=reference(m.TaskType,obj.title);obj.employee=employees.get(raw.get('ID_MANAGER_EXE')) or employees.get(raw.get('ID_MANAGER'))
        if not obj.done and raw['ID_COMPANY'] in latest:
            obj.contract=latest[raw['ID_COMPANY']][1];linked_tasks+=1
    report['counts']['tasks_linked_to_latest_contract']=linked_tasks
    report['counts']['unfinished_tasks_without_contract']=sum(not t.done and not t.contract_id for _,t in targets['tasks'])
    m.Task.objects.bulk_create([o for _,o in targets['tasks']],batch_size=100)
    for key,obj in targets['tasks']:bind('LIST_CONTACT_COMPANY',key,obj)
    progress('Исходные записи и сверка')
    records=[]
    for table,rows in i.items():
        for key,raw in rows.items():
            label,pk=bindings.get((table,key),('',None))
            status='deferred' if table=='LIST_MANYS' and not label else 'imported' if label else 'retained'
            records.append(m.LegacyRecord(source_key=source,table=table,source_id=key,import_run=run,payload=raw,target_model=label,target_id=pk,status=status))
    records.extend(m.LegacyRecord(source_key=source,table='@operator_opening',source_id=key,import_run=run,payload={'source_document_id':key,'basis':'aggregate_operator_payment'},target_model=obj._meta.label,target_id=obj.pk) for key,obj in opening)
    m.LegacyRecord.objects.bulk_create(records,batch_size=100)
    # Query actual persisted amounts, not only prepared values, before committing.
    def total(model,table,field):
        ids=[pk for (t,_),(_,pk) in bindings.items() if t==table]
        return (model.objects.filter(pk__in=ids).aggregate(s=m.Sum(field))['s'] or Decimal('0')).quantize(Decimal('.01'))
    if total(m.ContractLine,'LIST_TOVAR_DOC','amount')!=Decimal(report['totals']['lines']):raise HistoryImportError('Не сошлись суммы строк после записи.')
    if total(m.Contract,'LIST_DOCUMENTS','legacy_amount_adjustment')+total(m.ContractLine,'LIST_TOVAR_DOC','amount')!=Decimal(report['totals']['contracts']):raise HistoryImportError('Не сошлись итоги договоров.')
    actual_operator=sum((p.amount*(-1 if p.kind=='operator_refund' else 1) for p in m.Payment.objects.filter(pk__in=[o.pk for _,o in opening])),Decimal('0'))
    if total(m.Contract,'LIST_DOCUMENTS','opening_operator_paid')+actual_operator!=Decimal(report['totals']['operator_paid']):raise HistoryImportError('Не сошлись суммы оплаты ТО.')
    net=sum((o.amount*(-1 if o.kind=='customer_refund' else 1) for o in m.Payment.objects.filter(pk__in=[o.pk for _,o in targets['payments']])),Decimal('0'))
    if net!=Decimal(report['totals']['customer_net']):raise HistoryImportError('Не сошлись суммы клиентских платежей.')
    run.summary=report;run.issues=issues;run.save(update_fields=['summary','issues'])
    m.AuditEvent.objects.create(actor=actor,object_type='crm.LegacyImportRun',object_id=str(run.pk),action='legacy_history_imported',changes={'counts':report['counts'],'issues':len(issues)})
    return run,True
