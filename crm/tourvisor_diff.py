"""Human-readable comparisons use the same normalized values as the importer."""
import json
from difflib import SequenceMatcher
from datetime import date,datetime
from decimal import Decimal
from .models import Customer,Contract,Tourist,Task
from .tourvisor import GROUPS
from .templatetags.money import money

LABELS={'name':'Название','country':'Страна','region':'Регион','startdate':'Дата начала','nights':'Ночей','room':'Категория номера','meal':'Питание','placement':'Размещение','direction':'Направление','number':'Рейс','datefrom':'Дата вылета','dateto':'Дата прилёта','timefrom':'Время вылета','timeto':'Время прилёта','aircompany':'Авиакомпания','plane':'Самолёт','terminalfrom':'Аэропорт вылета','terminalto':'Аэропорт прилёта','terminalcodefrom':'Код аэропорта вылета','terminalcodeto':'Код аэропорта прилёта'}

def canonical(value):
    if value is None or value=='':return ''
    if isinstance(value,(date,datetime)):return value.isoformat()
    if isinstance(value,bool):return '1' if value else '0'
    if isinstance(value,Decimal):return format(value.normalize(),'f')
    return str(value).strip()

def display(value):
    if value is None or value=='':return '—'
    if isinstance(value,bool):return 'Да' if value else 'Нет'
    if isinstance(value,(date,datetime)):return value.strftime('%d.%m.%Y')
    if isinstance(value,Decimal):return money(value)
    return str(value)

def add_change(changes,label,old,new,force=False):
    if force or canonical(old)!=canonical(new):changes.append({'label':str(label),'old':display(old),'new':display(new)})

def array_diff(old,new,group):
    if group=='service':
        old=[{'name':v.get('name','')} for v in old];new=[{'name':v.get('name','')} for v in new]
    stable=lambda v:json.dumps({k:canonical(x) for k,x in v.items()},sort_keys=True,ensure_ascii=False)
    if sorted(stable(v) for v in old)==sorted(stable(v) for v in new):return []
    remaining=list(old);changed_new=[]
    for entry in new:
        index=next((i for i,v in enumerate(remaining) if stable(v)==stable(entry)),None)
        if index is None:changed_new.append(entry)
        else:remaining.pop(index)
    pairs=[]
    if group=='service':
        # No stable service IDs exist. Match only similar names; never pair an
        # unrelated deleted service with a renamed service just by row position.
        candidates=sorted(((SequenceMatcher(None,canonical(a.get('name')).casefold(),canonical(b.get('name')).casefold()).ratio(),i,j) for i,a in enumerate(remaining) for j,b in enumerate(changed_new)),reverse=True)
        used_old=set();used_new=set()
        for score,i,j in candidates:
            if score>=0.55 and i not in used_old and j not in used_new:
                pairs.append((remaining[i],changed_new[j]));used_old.add(i);used_new.add(j)
        pairs.extend((a,{}) for i,a in enumerate(remaining) if i not in used_old)
        pairs.extend(({},b) for j,b in enumerate(changed_new) if j not in used_new)
    else:
        pairs=[(remaining[i] if i<len(remaining) else {},changed_new[i] if i<len(changed_new) else {}) for i in range(max(len(remaining),len(changed_new)))]
    changes=[]
    for index,(a,b) in enumerate(pairs):
        for key in dict.fromkeys([*a,*b]):
            label='Отель' if group=='hotel' and key=='name' else LABELS.get(key,key)
            if group=='hotel' and max(len(old),len(new))>1:label=f'Отель {index+1} · {label}'
            add_change(changes,label,a.get(key),b.get(key))
    return changes

def compare_order(existing,normalized):
    result=[]
    def section(key,changes):result.append({'key':key,'label':GROUPS[key],'changes':changes,'changed':bool(changes)})
    changes=[]
    for field,value in normalized['customer'].items():
        add_change(changes,Customer._meta.get_field(field).verbose_name,getattr(existing.customer,field) if existing else None,value,force=existing is None and value not in ('',None))
    section('customer',changes)
    changes=[]
    for field,value in normalized['contract'].items():
        if field in ('number','date','tourvisor_time','hotel','region','room','meal'):continue
        if field=='end' and value is None and existing:continue
        add_change(changes,Contract._meta.get_field(field).verbose_name,getattr(existing,field) if existing else None,value,force=existing is None and value not in ('',None))
    add_change(changes,'Туроператор',existing.operator.name if existing else None,normalized['operator'])
    add_change(changes,'Комментарий из Турвизора',existing.source_data.get('comments','') if existing else None,normalized.get('comments',''))
    section('tour',changes)
    current={}
    if existing:
        for line in existing.lines.exclude(source_tourist_key='').select_related('tourist'):
            if line.tourist:current[line.source_tourist_key]=line.tourist
    incoming=dict(normalized['tourists']);changes=[]
    for key in dict.fromkeys([*current,*incoming]):
        old=current.get(key);new=incoming.get(key)
        name=new.get('name') if new else old.name
        if old is None:
            add_change(changes,'Добавлен турист',None,name)
            for field,value in new.items():
                if value not in ('',None):add_change(changes,Tourist._meta.get_field(field).verbose_name,None,value)
        elif new is None:add_change(changes,'Удалён из импортированного состава',name,None)
        else:
            for field,value in new.items():
                model_field=Tourist._meta.get_field(field)
                choices=dict(model_field.choices or [])
                add_change(changes,model_field.verbose_name,choices.get(getattr(old,field),getattr(old,field)),choices.get(value,value))
    section('tourists',changes)
    for group in ('hotel','transport','service'):
        previous=[dict(row) for row in existing.source_data.get(group,[])] if existing else []
        if group=='hotel' and existing:
            # The first imported hotel is mirrored in editable contract fields.
            # Compare that logical value once, using the actual current CRM value.
            if not previous and any(getattr(existing,f) for f in ('hotel','region','room','meal')):previous=[{}]
            if previous:
                for field,key in [('hotel','name'),('region','region'),('room','room'),('meal','meal')]:previous[0][key]=getattr(existing,field)
        changes=array_diff(previous,normalized[group],group)
        section(group,changes)
    changes=[];add_change(changes,'Стоимость договора, ₽',existing.amount if existing else None,normalized['price'])
    section('amount',changes)
    return result

def task_moves(contract,normalized,end=None):
    """Shift outstanding template tasks by the trip-date delta, preserving manual offsets."""
    future=normalized['contract']
    start=future.get('start');end=end or future.get('end') or contract.end
    moves=[]
    for task in Task.objects.filter(contract=contract,done=False).select_related('template'):
        if not task.template or task.template.anchor not in ('start','end'):continue
        old_anchor=contract.start if task.template.anchor=='start' else contract.end
        new_anchor=start if task.template.anchor=='start' else end
        if not old_anchor or not new_anchor or old_anchor==new_anchor:continue
        # Keep a custom due date's offset to the trip instead of replacing it with the template default.
        proposed=task.due+(new_anchor-old_anchor)
        moves.append({'task':task,'old':task.due,'new':proposed,'anchor':'start' if task.template.anchor=='start' else 'end','old_anchor':old_anchor,'new_anchor':new_anchor})
    return moves
