"""Staff-only synthetic-data probe for the agency's Tourvisor booking page."""
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

ORIGINS={'https://aborigen-tour.ru','https://www.aborigen-tour.ru'}

@require_GET
@never_cache
def demo(request):
    origin=request.headers.get('Origin','')
    if origin not in ORIGINS:
        return JsonResponse({'error':'Источник не разрешён.'},status=403)
    allowed=request.user.is_authenticated and request.user.is_active and request.user.has_perm('crm.view_contract')
    response=JsonResponse({'enabled':False},status=403) if not allowed else JsonResponse({
        'enabled':True,'test_only':True,
        'customer':{'Name':'Тестовый Заказчик Примерович','Phone':'+79990000000','Email':'test@example.invalid','Address':'Тестовый адрес','Birthday':'01.01.1980','PassportNumber':'0000 000001','PassportIssue':'01.02.2020','PassportAuthority':'Тестовый орган выдачи','PassportAuthorityCode':'000-000'},
        'tourists':[
            {'SURNAME':'TESTOV','NAME':'IVAN','BIRTHDAY':'01.01.1980','PASSPORTNUMBER':'00 0000001','PASSPORTISSUE':'01.02.2020','PASSPORTEXPIRY':'01.02.2030','PASSPORTAUTHORITY':'TEST'},
            {'SURNAME':'PROBNY','NAME':'PETR','BIRTHDAY':'02.02.1982','PASSPORTNUMBER':'00 0000002','PASSPORTISSUE':'01.02.2020','PASSPORTEXPIRY':'01.02.2030','PASSPORTAUTHORITY':'TEST'},
        ]})
    response['Access-Control-Allow-Origin']=origin
    response['Access-Control-Allow-Credentials']='true'
    response['Vary']='Origin, Cookie'
    response['X-Content-Type-Options']='nosniff'
    return response

# Real data is selected in the authenticated CRM; only its ID/expiry lives in session.
from datetime import timedelta
from django.contrib.auth.decorators import login_required,permission_required
from django.shortcuts import render,redirect,get_object_or_404
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import Contract

READ_PERMISSIONS=('crm.view_contract','crm.view_customer','crm.view_tourist')
SELECTION='booking_prefill_selection'

def age_on(birthday,start):
    return start.year-birthday.year-((start.month,start.day)<(birthday.month,birthday.day))

def access(request):
    return request.user.is_authenticated and request.user.is_active and request.user.has_perms(READ_PERMISSIONS)

def reply(request,payload,status=200):
    response=JsonResponse(payload,status=status)
    response['Cache-Control']='private, no-store, max-age=0'
    response['Vary']='Origin, Cookie'
    response['X-Content-Type-Options']='nosniff'
    origin=request.headers.get('Origin','')
    if origin in ORIGINS:
        response['Access-Control-Allow-Origin']=origin
        response['Access-Control-Allow-Credentials']='true'
    return response

def selected_contract(request):
    saved=request.session.get(SELECTION,{})
    if saved.get('expires',0)<=timezone.now().timestamp():return None
    return Contract.objects.select_related('customer','operator').filter(pk=saved.get('id'),exchange_id=saved.get('exchange_id')).first()

@require_GET
@never_cache
def status(request):
    if request.headers.get('Origin') not in ORIGINS or not access(request):return reply(request,{'enabled':False},403)
    contract=selected_contract(request)
    return reply(request,{'enabled':True,'contract':{'id':contract.pk,'number':str(contract)} if contract else None})

@login_required
@permission_required(READ_PERMISSIONS,raise_exception=True)
@never_cache
def select(request):
    if request.method not in ('GET','POST'):
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET','POST'])
    error=''
    if request.method=='POST':
        key=request.POST.get('contract','')
        if not key.isdecimal() or len(key)>18:error='Выберите договор.'
        else:
            contract=get_object_or_404(Contract,pk=key)
            request.session[SELECTION]={'id':contract.pk,'exchange_id':str(contract.exchange_id),'expires':(timezone.now()+timedelta(minutes=30)).timestamp()}
            from django.contrib import messages
            messages.success(request,'Данные договора подготовлены. На сайте АБОРИГЕН ТУР нажмите «Заполнить из договора».')
            return redirect('contract_card',pk=contract.pk)
    query=request.GET.get('q','').strip()[:100]
    contracts=Contract.objects.select_related('customer','operator').order_by('-date','-pk')
    specific=request.GET.get('contract','')
    if specific.isdecimal() and len(specific)<=18:contracts=contracts.filter(pk=specific)
    elif query:contracts=contracts.filter(Q(number__icontains=query)|Q(customer__name__icontains=query))
    return render(request,'crm/booking_prefill_select.html',{'contracts':contracts[:50],'selected':selected_contract(request),'query':query,'error':error})

@require_GET
@never_cache
@transaction.atomic
def data(request):
    if request.headers.get('Origin') not in ORIGINS or not access(request):return reply(request,{'enabled':False},403)
    contract=selected_contract(request)
    if not contract:return reply(request,{'error':'Выберите договор в CRM. Выбор действует 30 минут.'},409)
    tourists=[];seen=set()
    start=None
    if request.GET.get('start'):
        from django import forms
        try:start=forms.DateField().clean(request.GET['start'])
        except forms.ValidationError:return reply(request,{'error':'Укажите корректную дату начала новой поездки.'},400)
    if not start:return reply(request,{'error':'Укажите дату начала новой поездки.'},422)
    def day(value):return value.strftime('%d.%m.%Y') if value else ''
    import re
    for line in contract.lines.select_related('tourist').order_by('pk'):
        person=line.tourist
        if not person or person.pk in seen:continue
        seen.add(person.pk)
        label=str(person);person_issues=[]
        if not person.birthday:person_issues.append(f'{label}: не указана дата рождения.')
        age=age_on(person.birthday,start) if person.birthday and start else None
        if age is not None and age<0:person_issues.append(f'{label}: дата рождения позже начала тура.')
        if not person.surname or not person.given_name:person_issues.append(f'{label}: заполните фамилию и имя по паспорту.')
        if person.passport_type=='0' and not all(re.fullmatch(r"[A-Za-z][A-Za-z '\-]*",value or '') for value in (person.surname,person.given_name)):person_issues.append(f'{label}: для загранпаспорта нужны имя и фамилия латиницей.')
        if person.gender not in ('male','female'):person_issues.append(f'{label}: не указан пол.')
        tourists.append({'issues':person_issues,'id':person.pk,'age':age,'birthday_iso':person.birthday.isoformat() if person.birthday else '',
            'gender':person.gender,'nationality':person.nationality,'document_type':person.passport_type,
            'SURNAME':person.surname,'NAME':person.given_name,'BIRTHDAY':day(person.birthday),'PASSPORTNUMBER':person.passport_number,
            'PASSPORTISSUE':day(person.issued),'PASSPORTEXPIRY':day(person.expires),'PASSPORTAUTHORITY':person.issued_by})
    tourists.sort(key=lambda item:(item['birthday_iso'],item['id']))
    customer=contract.customer
    if customer.kind!='person':return reply(request,{'error':'Покупатель в форме Турвизора должен быть физическим лицом. В договоре выбрано юридическое лицо.'},422)
    return reply(request,{'enabled':True,'test_only':False,'contract':{'id':contract.pk,'number':str(contract),'start':start.isoformat()},
        'customer':{'Name':customer.name,'Phone':customer.main_phone,'Email':customer.main_email,'Address':customer.address,
            'Birthday':day(customer.birthday),'PassportNumber':customer.passport_number,'PassportIssue':day(customer.passport_issued),
            'PassportAuthority':customer.passport_issued_by,'PassportAuthorityCode':customer.passport_code},'tourists':tourists})
