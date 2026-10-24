"""Journal filtering uses Unicode casefold on SQLite as well as PostgreSQL."""
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from .models import Contract,normalize_location
from .templatetags.money import money
from .customer_matching import phone_key

COLUMNS=[('number','Договор'),('date','Дата'),('customer','Заказчик'),('operator','ТО'),('country','Страна'),('hotel','Отель'),('start','Начало'),('end','Окончание'),('amount','Сумма'),('paid','Оплачено'),('debt','Долг'),('cost','Себестоимость'),('profit','Доход'),('operator_due','Срок оплаты ТО'),('payment_method','Способ оплаты'),('notes','Примечание'),('departure','Город вылета'),('operator_paid','Дата оплаты ТО'),('adults','Взр'),('children','Дети')]
MONEY={'amount','paid','debt','cost','profit'}
DATES={'date','start','end','operator_due','operator_paid'}

def journal_context(params,dateform):
    start=params.get('start','');end=params.get('end','')
    today=timezone.localdate()
    if params.get('period')=='today':start=end=today.isoformat()
    elif params.get('period')=='month':
        start=today.replace(day=1).isoformat()
        end=((today.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)).isoformat()
    data=params.copy();data['start']=start;data['end']=end
    dateform=dateform(data)
    qs=Contract.objects.select_related('customer','operator','payment_method').prefetch_related('lines','payments').order_by('-date','-pk')
    if dateform.is_valid():
        if dateform.cleaned_data['start']:qs=qs.filter(date__gte=dateform.cleaned_data['start'])
        if dateform.cleaned_data['end']:qs=qs.filter(date__lte=dateform.cleaned_data['end'])
    rows=[]
    for contract in qs:
        customer=contract.customer
        fields={'customer':customer.name,'email':' '.join([customer.main_email,customer.emails]),'phone':' '.join([customer.main_phone,customer.phones]),'number':str(contract),'operator':str(contract.operator),'country':contract.country}
        if any((not any(phone_key(params[k]) in phone_key(v) for v in [customer.main_phone,*customer.phones.splitlines()])) if k=='phone' else (normalize_location(params[k]) not in normalize_location(fields[k])) for k in fields if params.get(k)):continue
        amounts={kind:sum((p.amount for p in contract.payments.all() if p.kind==kind),Decimal('0')) for kind in ('customer','customer_refund','operator','operator_refund')}
        amount=sum((l.amount for l in contract.lines.all()),Decimal('0'))
        paid=amounts['customer']-amounts['customer_refund'];cost=amounts['operator']-amounts['operator_refund']
        computed={'number':str(contract),'customer':customer.name,'operator':str(contract.operator),'payment_method':str(contract.payment_method) if contract.payment_method else '', 'amount':amount,'paid':paid,'cost':cost,'debt':amount-paid,'profit':amount-cost}
        values={key:computed[key] if key in computed else getattr(contract,key) for key,_ in COLUMNS}
        cells=[]
        for key,label in COLUMNS:
            value=values[key]
            text=money(value) if key in MONEY else (value.strftime('%d.%m.%Y') if value and key in DATES else str(value) if value is not None else '')
            cells.append({'key':key,'text':text,'filter_value':text or '—'})
        rows.append({'contract':contract,'cells':cells,'values':values})
    columns=[]
    for i,(key,label) in enumerate(COLUMNS):
        selected=params.getlist('f_'+key)
        choices=sorted({r['cells'][i]['filter_value'] for r in rows}|set(selected),key=normalize_location)
        columns.append({'key':key,'label':label,'options':[{'value':v,'selected':v in selected} for v in choices],'active':bool(selected),'direction':'↑' if params.get('sort')==key else '↓' if params.get('sort')=='-'+key else '', 'sort':('-' if params.get('sort')==key else '')+key})
    rows=[r for r in rows if all(not params.getlist('f_'+c['key']) or c['filter_value'] in params.getlist('f_'+c['key']) for c in r['cells'])]
    sort=params.get('sort','');key=sort.lstrip('-')
    if key in dict(COLUMNS):
        present=[r for r in rows if r['values'][key] is not None];missing=[r for r in rows if r['values'][key] is None]
        present.sort(key=lambda r:normalize_location(r['values'][key]) if isinstance(r['values'][key],str) else r['values'][key],reverse=sort.startswith('-'));rows=present+missing
    totals={key:sum((r['values'][key] for r in rows),Decimal('0')) for key in MONEY}
    footer=[{'key':key,'text':money(totals[key]) if key in MONEY else f'ИТОГО: {len(rows)}' if key=='number' else ''} for key,_ in COLUMNS]
    return {'rows':[r['contract'] for r in rows],'table_rows':rows,'columns':columns,'footer':footer,'totals':totals,'count':len(rows),'dateform':dateform,'start_value':start,'end_value':end,'sort':sort}
