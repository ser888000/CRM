"""Human-readable comparisons use the same normalized values as the importer."""
import json
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
    # Service start dates are deliberately not imported into working fields.
    if group=='service':
        old=[{'name':v.get('name','')} for v in old];new=[{'name':v.get('name','')} for v in new]
    stable=lambda v:json.dumps({k:canonical(x) for k,x in v.items()},sort_keys=True,ensure_ascii=False)
    old=sorted(old,key=stable);new=sorted(new,key=stable)
    if [stable(v) for v in old]==[stable(v) for v in new]:return []
    # Match an unchanged row first, then pair remaining rows to show actual field changes.
    remaining=list(old);changed_new=[]
    for entry in new:
        index=next((i for i,v in enumerate(remaining) if stable(v)==stable(entry)),None)
        if index is None:changed_new.append(entry)
        else:remaining.pop(index)
    changes=[]
    for i in range(max(len(remaining),len(changed_new))):
        a=remaining[i] if i<len(remaining) else {};b=changed_new[i] if i<len(changed_new) else {}
        title=b.get('number') or b.get('name') or a.get('number') or a.get('name') or f'Запись {i+1}'
        for key in dict.fromkeys([*a,*b]):
            add_change(changes,f'{title} · {LABELS.get(key,key)}',a.get(key),b.get(key))
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
                if value not in ('',None):add_change(changes,f'{name} · {Tourist._meta.get_field(field).verbose_name}',None,value)
        elif new is None:add_change(changes,'Удалён из импортированного состава',name,None)
        else:
            for field,value in new.items():
                model_field=Tourist._meta.get_field(field)
                choices=dict(model_field.choices or [])
                add_change(changes,f'{name} · {model_field.verbose_name}',choices.get(getattr(old,field),getattr(old,field)),choices.get(value,value))
    section('tourists',changes)
    for group in ('hotel','transport','service'):
        changes=array_diff(existing.source_data.get(group,[]) if existing else [],normalized[group],group)
        if group=='hotel' and existing:
            for field in ('hotel','region','room','meal'):
                add_change(changes,Contract._meta.get_field(field).verbose_name,getattr(existing,field),normalized['contract'].get(field,''))
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
