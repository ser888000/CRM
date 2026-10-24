"""Conservative customer reuse: normalized name and non-conflicting contacts."""
import re
from .models import Customer,normalize_location


def phone_key(value):
    digits=re.sub(r'\D','',value)
    if len(digits)==11 and digits[0] in '78':digits='7'+digits[1:]
    if len(digits)==10:digits='7'+digits
    return digits


def contacts(data,kind):
    main=data.get('main_'+kind,'') or ''
    extra=data.get('phones' if kind=='phone' else 'emails','') or ''
    values=[main,*re.split(r'[\n;,]+',extra)]
    normalize=phone_key if kind=='phone' else lambda v:v.strip().casefold()
    return {normalize(v) for v in values if normalize(v)}


def customer_matches(data):
    exact=[];similar=[]
    incoming_name=normalize_location(data['name'])
    p=contacts(data,'phone');e=contacts(data,'email')
    for customer in Customer.objects.all():
        current={key:getattr(customer,key) for key in ('main_phone','main_email','phones','emails')}
        cp=contacts(current,'phone');ce=contacts(current,'email')
        same_name=normalize_location(customer.name)==incoming_name
        same_phone=bool(p & cp);same_email=bool(e & ce)
        conflict=bool(p and cp and not same_phone) or bool(e and ce and not same_email)
        if same_name and (same_phone or same_email) and not conflict:exact.append(customer)
        if same_name or same_phone or same_email:similar.append(customer)
    return (exact[0] if len(exact)==1 else None),similar
