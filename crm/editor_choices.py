"""Shared, bounded party and contract choices for task and finance editors."""
from .models import Customer,Contract,normalize_location
from .financial_queries import with_financials
from .templatetags.money import money

def customer_label(customer):
    return ' · '.join(filter(None,[customer.name,customer.birthday.strftime('%d.%m.%Y') if customer.birthday else None,customer.main_phone or customer.phones]))

def contract_label(contract,include_amount=True):
    if not include_amount:return f'{contract.number or "Без номера"} · {contract.date:%d.%m.%Y} · {contract.customer}'
    return f'{contract.number or "Без номера"} · {contract.date:%d.%m.%Y} · {money(contract.amount)} ₽ · {contract.customer}'

def customers(query):
    from .customer_matching import phone_key
    query=normalize_location(query[:250]);digits=phone_key(query);result=[]
    if len(query)<2:return result
    for c in Customer.objects.filter(is_hidden=False).only('id','name','birthday','main_phone','phones','main_email').order_by('name','pk'):
        if query in normalize_location(customer_label(c)+' '+c.main_email) or (digits and digits in phone_key(c.main_phone+' '+c.phones)):
            result.append({'id':c.pk,'label':customer_label(c)})
            if len(result)==30:break
    return result

def contracts(query='',customer='',include_amount=True):
    query=normalize_location(query[:250]);qs=Contract.objects.order_by('-date','-pk')
    if customer:
        if not customer.isdecimal() or len(customer)>18:return []
        qs=qs.filter(customer_id=customer)
    ids=[]
    for pk,number,date,name in qs.values_list('pk','number','date','customer__name'):
        if query and query not in normalize_location(number+' '+date.strftime('%d.%m.%Y')+' '+name):continue
        ids.append(pk)
        if len(ids)==30:break
    return [{'id':c.pk,'label':contract_label(c,include_amount)} for c in with_financials(qs.filter(pk__in=ids)).select_related('customer').only('id','number','date','legacy_amount_adjustment','opening_operator_paid','customer__name')]

def configure(form,customer_url,contract_url,include_amount=True):
    form.fields['customer'].label_from_instance=customer_label
    form.fields['contract'].queryset=with_financials(form.fields['contract'].queryset).select_related('customer')
    form.fields['contract'].label_from_instance=lambda contract:contract_label(contract,include_amount)
    for name,url in [('customer',customer_url),('contract',contract_url)]:
        field=form.fields[name]
        current=getattr(form.instance,name+'_id',None) or form.initial.get(name) or field.initial
        if hasattr(current,'pk'):current=current.pk
        if form.is_bound and not field.disabled:current=form.data.get(form.add_prefix(name))
        field.widget.choices=[('','---------')]+[(obj.pk,field.label_from_instance(obj)) for obj in field.queryset.filter(pk=current)] if current and str(current).isdigit() else [('','---------')]
        field.widget.attrs.update({'data-remote-choices':url,'data-search-label':'Найти заказчика' if name=='customer' else 'Найти договор по номеру или дате'})
        if name=='contract':field.widget.attrs.update({'data-customer-filter':form['customer'].id_for_label,'data-browse':'1','data-min-length':'1'})
