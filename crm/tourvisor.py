"""Read-only Tourvisor API client and explicit, transactional contract import."""
import hashlib
import json
import os
import re
from datetime import datetime
from decimal import Decimal,InvalidOperation
from urllib import request,error,parse
from django.core.exceptions import ValidationError
from django.db import transaction,IntegrityError
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from .models import Contract,Customer,Operator,Tourist,ContractLine,AuditEvent,DepartureCity,Country,Task
from .services import create_tasks,flight_description

GROUPS={'customer':'Заказчик','tour':'Параметры тура','tourists':'Туристы','hotel':'Проживание','transport':'Перелёты','service':'Услуги','amount':'Стоимость договора'}
class TourvisorError(Exception):pass

MIN_TOURVISOR_ID=2299358

def check_import_boundary(source_id):
    if int(source_id)<MIN_TOURVISOR_ID:
        raise TourvisorError('Импорт новых договоров разрешён начиная с № 2299358 включительно. Более ранние договоры перенесены из старой CRM.')

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

@sensitive_variables()
def _fetch_online_data(parameters,max_bytes=2000000):
    key=os.getenv('TOURVISOR_API_KEY')
    if not key:raise TourvisorError('На сервере не настроен ключ TOURVISOR_API_KEY. Обратитесь к администратору.')
    url='https://tourvisor.ru/xml/ordersonline.php?'+parse.urlencode({'authkey':key,'format':'json',**parameters})
    try:
        with request.build_opener(NoRedirect()).open(url,timeout=25) as response:
            raw=response.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError
        data=json.loads(raw)
    except error.HTTPError as exc:
        if exc.code in (401,403):raise TourvisorError('Турвизор отклонил доступ. Проверьте API-ключ и права.') from None
        raise TourvisorError('Турвизор временно недоступен. Попробуйте позже. Данные CRM не изменены.') from None
    except (error.URLError,TimeoutError,OSError,ValueError):
        raise TourvisorError('Не удалось получить данные из Турвизора. Попробуйте позже. Данные CRM не изменены.') from None
    if not isinstance(data,dict):raise TourvisorError('Турвизор вернул неожиданный ответ. Данные CRM не изменены.')
    if 'error' in data:
        e=data['error']
        if isinstance(e,dict) and 'authorisation' in str(e.get('errormessage','')).lower():
            raise TourvisorError('Турвизор отклонил API-ключ. Проверьте ключ и права доступа.')
        raise TourvisorError('Турвизор вернул ошибку. Попробуйте позже. Данные CRM не изменены.')
    return data


def _online_entries(data):
    orders=data.get('orders')
    if not isinstance(orders,dict):raise TourvisorError('Турвизор вернул неожиданный список онлайн-заявок. Повторите позже.')
    entries=orders.get('order',[])
    if entries in (None,''):entries=[]
    if isinstance(entries,dict):entries=[entries]
    if not isinstance(entries,list) or not all(isinstance(v,dict) for v in entries):
        raise TourvisorError('Турвизор вернул неожиданный список онлайн-заявок. Повторите позже.')
    return entries


@sensitive_variables()
def fetch_order(order_id):
    if not re.fullmatch(r'[0-9]{1,20}',str(order_id)):
        raise TourvisorError('Укажите числовой ID онлайн-заявки.')
    entries=_online_entries(_fetch_online_data({'id':order_id}))
    if not entries:raise TourvisorError('Онлайн-заявка с таким ID не найдена.')
    if len(entries)!=1 or str(entries[0].get('id'))!=str(order_id):
        raise TourvisorError('Турвизор вернул неожиданный состав заявки. Данные CRM не изменены.')
    normalize_order(entries[0])
    return entries[0]


@sensitive_variables()
def fetch_orders(limit=25,lastid=''):
    if limit not in (25,50,100) or (lastid and not re.fullmatch(r'[0-9]{1,20}',str(lastid))):
        raise TourvisorError('Выберите 25, 50 или 100 заявок и числовой начальный ID.')
    parameters={'limit':limit}
    if lastid:parameters['lastid']=lastid
    entries=_online_entries(_fetch_online_data(parameters,max_bytes=8000000))
    ids=[str(v.get('id','')) for v in entries]
    if len(entries)>limit or len(ids)!=len(set(ids)) or any(not re.fullmatch(r'[0-9]{1,20}',v) for v in ids):
        raise TourvisorError('Турвизор вернул неожиданный состав списка. Данные CRM не изменены.')
    return entries

def day(value,required=False):
    if value in ('',None):
        if required:raise ValueError
        return None
    return datetime.strptime(str(value),'%d.%m.%Y').date()

def rows(order,key):
    value=order.get(key,[])
    if value in ('',None):return []
    if isinstance(value,dict):value=[value]
    if not isinstance(value,list) or len(value)>200 or not all(isinstance(v,dict) for v in value):raise ValueError
    return value

def text(value):return '' if value is None else str(value).strip()

def tour_flights(entries):
    return '\n'.join(' · '.join(text(e.get(k)) for k in ('number','datefrom','timefrom','terminalfrom','terminalto','dateto','timeto') if e.get(k)) for e in entries)

@sensitive_variables()
def normalize_order(o):
    try:
        currency=text(o.get('currency','RUB')).upper()
        if currency=='RUR':currency='RUB'
        if currency!='RUB':raise TourvisorError('Стоимость заявки указана не в рублях. Автоматический пересчёт пока не поддерживается; используйте ручной договор.')
        price=Decimal(str(o.get('price','')))
        if not price.is_finite() or price<0 or price>=Decimal('1000000000000') or price!=price.quantize(Decimal('0.01')):raise ValueError
        customer={
            'surname':text(o.get('surname')),'given_name':text(o.get('name')),'patronymic':text(o.get('otch')),
            'address':text(o.get('address')),'main_phone':text(o.get('phone')),'main_email':text(o.get('email')),
            'passport_number':text(o.get('client_pass_number')),'passport_issued':day(o.get('client_pass_issue_date')),
            'passport_issued_by':text(o.get('client_pass_issue_by')),'passport_code':text(o.get('client_pass_code')),
            'birthday':day(o.get('client_birthday'))}
        customer['name']=' '.join(customer[k] for k in ('surname','given_name','patronymic') if customer[k])
        if not customer['name'] or not text(o.get('operator')):raise ValueError
        hotels=rows(o,'hotel');flights=rows(o,'transport');services=rows(o,'service')
        contract={
            'number':text(o.get('id')),'date':day(o.get('date'),True),'tourvisor_time':text(o.get('time')),
            'country':text(o.get('country')),'departure':text(o.get('departure')),'start':day(o.get('flydate')),
            'tour_name':text(o.get('tour')),'source_currency':currency,
            'nights':int(o['nights']) if o.get('nights') not in ('',None) else None,
            'adults':int(o.get('adult') or 0),'children':int(o.get('child') or 0),'infants':int(o.get('infant') or 0)}
        for name,model in [('country',Country),('departure',DepartureCity)]:
            record=model.match(contract[name]) if contract[name] else None
            if record:contract[name]=record.name
        if hotels:
            h=hotels[0]
            contract.update(hotel=text(h.get('name')),region=text(h.get('region')),room=text(h.get('room')),meal=text(h.get('meal')))
        end_dates=[day(f.get('dateto')) for f in flights if str(f.get('direction'))=='2' and f.get('dateto')]
        contract['end']=max(end_dates) if end_dates else None
        tourists=[]
        for t in rows(o,'tourist'):
            full_name=' '.join(text(t.get(k)) for k in ('surname','name') if t.get(k))
            if not full_name:raise ValueError
            person={'name':full_name,'surname':text(t.get('surname')),'given_name':text(t.get('name')),
                    'gender':text(t.get('gender')),'birthday':day(t.get('birthdate')),
                    'passport_number':' '.join(text(t.get(k)) for k in ('passportseries','passportnumber') if t.get(k)),
                    'issued':day(t.get('passportissuedate')),'expires':day(t.get('passportenddate')),
                    'issued_by':text(t.get('passportissuedby')),'passport_type':text(t.get('passporttype')),
                    'birthcountry':text(t.get('birthcountry')),'nationality':text(t.get('nationality')),
                    'is_customer':str(t.get('isclient',t.get('is_client',0)))=='1'}
            identity=(person['passport_type'],person['passport_number']) if person['passport_number'] else (person['name'],str(person['birthday']))
            key=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
            if any(k==key for k,_ in tourists):raise ValueError
            tourists.append((key,person))
        # Validate complete model field limits before presenting a preview.
        Customer(**customer).full_clean(exclude=['id'])
        Contract(**contract).full_clean(exclude=['id','customer','operator','tourvisor_id','source_data'])
        for _,person in tourists:Tourist(**person).full_clean(exclude=['id','customer'])
        for group in (hotels,flights,services):
            for r in group:
                if any(isinstance(v,(dict,list)) for v in r.values()):raise ValueError
        return {'comments':text(o.get('comments')),'customer':customer,'contract':contract,'operator':text(o.get('operator')),'price':price,'tourists':tourists,'hotel':hotels,'transport':flights,'service':services}
    except TourvisorError:raise
    except (ValueError,TypeError,InvalidOperation,ValidationError,KeyError):
        raise TourvisorError('В заявке неполные или некорректные данные. Проверьте ФИО, ТО, даты, валюту и стоимость в Турвизоре. Данные CRM не изменены.') from None

@sensitive_variables()
@transaction.atomic
def apply_order(order,user,groups,templates=None,dates=None,expected=None,expected_version=None,end=None,task_updates=None,customer_choice='auto',update_customer=False):
    n=normalize_order(order);source_id=str(order['id'])
    if end is not None and n['contract']['start'] and end<n['contract']['start']:
        raise TourvisorError('Дата окончания тура раньше начала.')
    contract=Contract.objects.select_for_update().filter(tourvisor_id=source_id).first()
    if contract and expected is None:
        raise TourvisorError('Эта заявка уже импортирована. Загрузите предпросмотр повторно для сравнения.')
    if expected is not None and (not contract or contract.pk!=expected):
        raise TourvisorError('Договор изменился. Загрузите предпросмотр повторно.')
    if contract and expected_version is not None and str(contract.updated_at)!=expected_version:
        raise TourvisorError('Договор изменился. Загрузите предпросмотр повторно.')
    previous_flights=flight_description(contract) if contract else ''
    pending_moves=[]
    if task_updates:
        if not contract or 'tour' not in groups or not user.has_perm('crm.change_task'):
            raise TourvisorError('Перенос задач доступен только вместе с обновлением дат тура.')
        for change in task_updates:
            task=Task.objects.select_for_update().select_related('template').filter(pk=change['id'],contract=contract).first()
            if not task or task.done or str(task.due)!=change['old'] or task.template_id!=change['template'] or not task.template or task.template.anchor not in ('start','end') or change.get('anchor',task.template.anchor)!=task.template.anchor:
                raise TourvisorError('Задача изменилась после предпросмотра. Загрузите сверку повторно; изменения не сохранены.')
            anchor=task.template.anchor
            old_anchor=contract.start if anchor=='start' else contract.end
            new_anchor=n['contract']['start'] if anchor=='start' else (end or n['contract']['end'] or contract.end)
            if not old_anchor or not new_anchor or old_anchor==new_anchor:
                raise TourvisorError('Даты поездки для выбранной задачи не изменились. Снимите галочку переноса.')
            pending_moves.append((task,change['new']))
    new=contract is None
    if new:
        check_import_boundary(source_id)
        if not {'customer','tour','amount'}.issubset(groups):
            raise TourvisorError('Для нового договора выберите заказчика, параметры тура и стоимость.')
        # A manually entered contract may already have this number: never create an automatic duplicate.
        if Contract.objects.filter(number=source_id).exists():
            raise TourvisorError('В CRM уже есть договор с этим номером без связи с Турвизором. Автоматический импорт остановлен; сначала проверьте существующий договор.')
        if 'hotel' not in groups:
            for field in ('hotel','region','room','meal'):n['contract'].pop(field,None)
        from .customer_matching import customer_matches
        match,candidates=customer_matches(n['customer'])
        if customer_choice=='new':customer=Customer.objects.create(**n['customer'])
        elif customer_choice=='auto':
            if match:customer=Customer.objects.select_for_update().get(pk=match.pk)
            elif candidates:raise TourvisorError('Найдены похожие заказчики. Выберите существующего или создание нового.')
            else:customer=Customer.objects.create(**n['customer'])
        else:
            customer=next((c for c in candidates if str(c.pk)==str(customer_choice)),None)
            if not customer:raise TourvisorError('Список похожих заказчиков изменился. Загрузите заявку повторно.')
            customer=Customer.objects.select_for_update().get(pk=customer.pk)
        operator=Operator.objects.get_or_create(name=n['operator'])[0]
        contract=Contract.objects.create(customer=customer,operator=operator,tourvisor_id=source_id,**n['contract'])
    if 'customer' in groups and (not new or update_customer):
        customer=Customer.objects.select_for_update().get(pk=contract.customer_id)
        before={key:getattr(customer,key) for key in n['customer']}
        if any(before[key]!=value for key,value in n['customer'].items()):
            for key,value in n['customer'].items():setattr(customer,key,value)
            customer.save()
            contract.customer=customer
            AuditEvent.objects.create(actor=user,object_type='crm.Customer',object_id=str(customer.pk),action='tourvisor_updated',changes={key:{'old':str(before[key]),'new':str(value)} for key,value in n['customer'].items() if before[key]!=value})
    if 'tour' in groups and not new:
        for k,v in n['contract'].items():
            if k not in ('number','date','tourvisor_time','hotel','region','room','meal'):setattr(contract,k,v)
        contract.operator=Operator.objects.get_or_create(name=n['operator'])[0]
    if 'hotel' in groups:
        for field in ('hotel','region','room','meal'):setattr(contract,field,n['contract'].get(field,''))
    snapshot=dict(contract.source_data)
    for group in ('hotel','transport','service'):
        if group in groups:snapshot[group]=n[group]
    if end is not None and ('tour' in groups or new):contract.end=end
    if 'tour' in groups:
        snapshot['comments']=text(order.get('comments'))
        snapshot['manual']=order.get('manual')
    if 'tourists' in groups:
        snapshot['tourist']=rows(order,'tourist')
        keys=set()
        for key,person in n['tourists']:
            keys.add(key)
            line=contract.lines.filter(source_tourist_key=key).first()
            if line and line.tourist_id:
                tourist=line.tourist
                if tourist.contractline_set.exclude(contract=contract).exists():tourist.pk=None;tourist.is_default=False
                for k,v in person.items():setattr(tourist,k,v)
                tourist.customer=contract.customer if person['is_customer'] else None
                tourist.save();line.tourist=tourist;line.save()
            else:
                tourist=Tourist.objects.create(customer=contract.customer if person['is_customer'] else None,**person)
                ContractLine.objects.create(contract=contract,tourist=tourist,description=person['name'],amount=0,source_tourist_key=key)
        # Only imported zero-cost tourist rows can be removed. Financial lines are preserved.
        contract.lines.exclude(source_tourist_key='').exclude(source_tourist_key__in=keys).filter(amount=0).delete()
    if 'amount' in groups:
        delta=n['price']-contract.amount
        if delta:
            ContractLine.objects.create(contract=contract,description='Стоимость тура из Турвизора' if new else 'Корректировка стоимости из Турвизора',amount=delta)
    snapshot['id']=source_id
    contract.source_data=snapshot;contract.imported_at=timezone.now();contract.save()
    if new:create_tasks(contract,templates=templates or [],dates=dates)
    for task,new_due in pending_moves:
        old_due=task.due;task.due=new_due
        changes={'due':{'old':str(old_due),'new':str(new_due)}}
        if 'transport' in groups and task.template.copy_flights and previous_flights and task.description.startswith(previous_flights):
            old_description=task.description
            task.description=flight_description(contract)+old_description[len(previous_flights):]
            if task.description!=old_description:changes['description']={'old':old_description,'new':task.description}
        task.save(update_fields=['due','description'])
        AuditEvent.objects.create(actor=user,object_type='crm.Task',object_id=str(task.pk),action='rescheduled',changes=changes)
    AuditEvent.objects.create(actor=user,object_type='crm.Contract',object_id=str(contract.pk),action='tourvisor_created' if new else 'tourvisor_updated',changes={'groups':sorted(groups)})
    return contract
