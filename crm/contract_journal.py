from .column_search import matches as column_matches,decorate as decorate_columns
"""Journal filtering uses Unicode casefold on SQLite as well as PostgreSQL."""
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from .models import Contract,normalize_location
from .templatetags.money import money
from .customer_matching import phone_key

COLUMNS=[('number','Номер'),('date','Дата'),('customer','Заказчик'),('operator','ТО'),('country','Страна'),('hotel','Отель'),('start','Начало'),('end','Окончание'),('source_currency','Вал'),('amount','Сумма'),('paid','Оплачено'),('debt','Долг'),('cost','Себест'),('profit','Доход'),('operator_due','Срок ТО'),('payment_method','Способ оплаты'),('notes','Примечание'),('departure','Город вылета'),('operator_paid_in_full','Оплачено ТО'),('adults','Взр'),('children','Дети')]
MONEY={'amount','paid','debt','cost','profit'}
DATES={'date','start','end','operator_due'}

def journal_context(params,dateform):
    from .journal_period import prepare,has_value_filters,reset_link
    params=prepare(params)
    start=params['start'];end=params['end']
    dateform=dateform(params)
    search_all_dates=has_value_filters(params,('customer','email','phone','number','operator','country'))
    qs=Contract.objects.select_related('customer','operator','payment_method').prefetch_related('lines','payments').order_by('-date','-pk')
    if dateform.is_valid() and not search_all_dates:
        if dateform.cleaned_data['start']:qs=qs.filter(date__gte=dateform.cleaned_data['start'])
        if dateform.cleaned_data['end']:qs=qs.filter(date__lte=dateform.cleaned_data['end'])
    elif not dateform.is_valid():qs=qs.none()
    if search_all_dates:
        # Match light scalar values first; do not load every historical line/payment
        # just to locate a single customer outside the currently selected dates.
        from .models import Customer
        if any(params.get(k) for k in ('customer','email','phone')):
            ids=[]
            for c in Customer.objects.values('pk','name','main_phone','phones','main_email','emails'):
                if params.get('customer') and normalize_location(params['customer']) not in normalize_location(c['name']):continue
                if params.get('email') and normalize_location(params['email']) not in normalize_location(' '.join([c['main_email'],c['emails']])):continue
                if params.get('phone') and not any(phone_key(params['phone']) in phone_key(v) for v in [c['main_phone'],*c['phones'].splitlines()]):continue
                ids.append(c['pk'])
            qs=qs.filter(customer_id__in=ids)
        for field,lookup in [('number','number'),('country','country'),('operator','operator__name')]:
            if params.get(field):
                target=normalize_location(params[field])
                ids=[pk for pk,value in qs.values_list('pk',lookup) if target in normalize_location(value or '')]
                qs=qs.filter(pk__in=ids)
    rows=[]
    for contract in qs:
        customer=contract.customer
        fields={'customer':customer.name,'email':' '.join([customer.main_email,customer.emails]),'phone':' '.join([customer.main_phone,customer.phones]),'number':str(contract),'operator':str(contract.operator),'country':contract.country}
        if any((not any(phone_key(params[k]) in phone_key(v) for v in [customer.main_phone,*customer.phones.splitlines()])) if k=='phone' else (normalize_location(params[k]) not in normalize_location(fields[k])) for k in fields if params.get(k)):continue
        amounts={kind:sum((p.amount for p in contract.payments.all() if p.kind==kind),Decimal('0')) for kind in ('customer','customer_refund','operator','operator_refund')}
        amount=sum((l.amount for l in contract.lines.all()),Decimal('0'))+contract.legacy_amount_adjustment
        paid=amounts['customer']-amounts['customer_refund'];cost=contract.opening_operator_paid+amounts['operator']-amounts['operator_refund']
        computed={'number':str(contract),'customer':customer.name,'operator':str(contract.operator),'payment_method':str(contract.payment_method) if contract.payment_method else '', 'amount':amount,'paid':paid,'cost':cost,'debt':amount-paid,'profit':amount-cost}
        values={key:computed[key] if key in computed else getattr(contract,key) for key,_ in COLUMNS}
        cells=[]
        for key,label in COLUMNS:
            value=values[key]
            text=('Оплачено' if value else 'Не оплачено') if key=='operator_paid_in_full' else money(value) if key in MONEY else (value.strftime('%d.%m.%Y') if value and key in DATES else str(value) if value is not None else '')
            cells.append({'key':key,'text':text,'filter_value':text or '—'})
        rows.append({'contract':contract,'cells':cells,'values':values})
    columns=[]
    for i,(key,label) in enumerate(COLUMNS):
        selected=params.getlist('f_'+key)
        choices=sorted({r['cells'][i]['filter_value'] for r in rows}|set(selected),key=normalize_location)
        columns.append({'key':key,'label':label,'options':[{'value':v,'selected':v in selected} for v in choices],'active':bool(selected),'direction':'↑' if params.get('sort')==key else '↓' if params.get('sort')=='-'+key else '', 'sort':('-' if params.get('sort')==key else '')+key})
    rows=[r for r in rows if all(not params.getlist('f_'+c['key']) or c['filter_value'] in params.getlist('f_'+c['key']) for c in r['cells'])]
    rows=[r for r in rows if column_matches({c['key']:c['filter_value'] for c in r['cells']},params)]
    decorate_columns(columns,params)
    sort=params.get('sort','');key=sort.lstrip('-')
    if key in dict(COLUMNS):
        present=[r for r in rows if r['values'][key] is not None];missing=[r for r in rows if r['values'][key] is None]
        present.sort(key=lambda r:normalize_location(r['values'][key]) if isinstance(r['values'][key],str) else r['values'][key],reverse=sort.startswith('-'));rows=present+missing
    totals={key:sum((r['values'][key] for r in rows),Decimal('0')) for key in MONEY}
    totals.update({key:sum(r['values'][key] or 0 for r in rows) for key in ('adults','children')})
    footer=[{'key':key,'text':money(totals[key]) if key in MONEY else str(totals[key]) if key in ('adults','children') else f'ИТОГО: {len(rows)}' if key=='number' else ''} for key,_ in COLUMNS]
    return {'search_all_dates':search_all_dates,'reset_filters_url':reset_link('/',params),'rows':[r['contract'] for r in rows],'table_rows':rows,'columns':columns,'footer':footer,'totals':totals,'count':len(rows),'dateform':dateform,'start_value':start,'end_value':end,'sort':sort,'period':params['period']}
