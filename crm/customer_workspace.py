"""Customer directory in the main workspace, with shared person/company forms."""
import hashlib
import json
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required,permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count,Q,Sum
from django.forms.models import model_to_dict
from django.http import QueryDict
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from .models import Customer,Contract,Task,Payment,normalize_location
from .card_forms import CustomerCardForm
from .customer_matching import contacts,phone_key,customer_matches
from .card_views import audit

COLUMNS=[('name','Заказчик'),('kind','Тип'),('phone','Телефоны'),('email','E-mail'),('inn','ИНН'),('contracts','Договоров')]
PARAMS={'name','phone','email','kind','sort','page'}|{'f_'+key for key,_ in COLUMNS}

def safe_query(value):
    data=QueryDict(value[:8000]).copy()
    for key in list(data):
        if key not in PARAMS:del data[key]
    return data.urlencode()

def back_url(value):
    query=safe_query(value)
    return '/customers/'+('?' +query if query else '')

def version(customer):
    return hashlib.sha256(json.dumps(model_to_dict(customer),sort_keys=True,default=str).encode()).hexdigest()

class CustomerFilters(forms.Form):
    name=forms.CharField(label='ФИО, организация или ИНН',required=False,max_length=250)
    phone=forms.CharField(label='Телефон',required=False,max_length=100)
    email=forms.CharField(label='E-mail',required=False,max_length=250)
    kind=forms.ChoiceField(label='Тип заказчика',required=False,choices=[('','Все заказчики'),('person','Физическое лицо'),('company','Юридическое лицо')])


def matching_rows(data):
    rows=[]
    qs=Customer.objects.annotate(contract_count=Count('contract',distinct=True)).only('id','name','kind','main_phone','phones','main_email','emails','inn').order_by('name','pk')
    if data['kind']:qs=qs.filter(kind=data['kind'])
    for customer in qs:
        if normalize_location(data['name']) not in normalize_location(customer.name+' '+customer.inn):continue
        contact_data={key:getattr(customer,key) for key in ('main_phone','phones','main_email','emails')}
        if data['phone'] and (not phone_key(data['phone']) or not any(phone_key(data['phone']) in v for v in contacts(contact_data,'phone'))):continue
        if data['email'] and not any(data['email'].strip().casefold() in v for v in contacts(contact_data,'email')):continue
        values={'name':customer.name,'kind':customer.get_kind_display(),'phone':' · '.join(v for v in (customer.main_phone,customer.phones) if v),'email':' · '.join(v for v in (customer.main_email,customer.emails) if v),'inn':customer.inn,'contracts':customer.contract_count}
        cells=[{'key':key,'text':str(values[key]),'filter_value':str(values[key]) or '—'} for key,_ in COLUMNS]
        rows.append({'customer':customer,'values':values,'cells':cells})
    return rows

@login_required
@permission_required('crm.view_customer',raise_exception=True)
@never_cache
def journal(request):
    if 'reset' in request.GET:
        request.session.pop('customer_journal',None);return redirect('customers')
    if not request.GET and request.session.get('customer_journal'):return redirect(back_url(request.session['customer_journal']))
    filters=CustomerFilters(request.GET);rows=[]
    if filters.is_valid():
        data=filters.cleaned_data
        rows=matching_rows(data)
        request.session['customer_journal']=safe_query(request.GET.urlencode())
    columns=[]
    for index,(key,label) in enumerate(COLUMNS):
        selected=request.GET.getlist('f_'+key)
        values=sorted({r['cells'][index]['filter_value'] for r in rows}|set(selected),key=normalize_location)
        columns.append({'key':key,'label':label,'remote':len(values)>100,'options':[{'value':v,'selected':v in selected} for v in dict.fromkeys([*selected,*values[:100]])],'active':bool(selected),'direction':'↑' if request.GET.get('sort')==key else '↓' if request.GET.get('sort')=='-'+key else '', 'sort':('-' if request.GET.get('sort')==key else '')+key})
    rows=[r for r in rows if all(not request.GET.getlist('f_'+c['key']) or c['filter_value'] in request.GET.getlist('f_'+c['key']) for c in r['cells'])]
    sort=request.GET.get('sort','name');key=sort.lstrip('-')
    if key in dict(COLUMNS):rows.sort(key=lambda r:r['values'][key] if key=='contracts' else normalize_location(r['values'][key]),reverse=sort.startswith('-'))
    count=len(rows);page=Paginator(rows,100).get_page(request.GET.get('page'));pagination=[]
    for number,label in [(page.previous_page_number() if page.has_previous() else None,'← Назад'),(page.next_page_number() if page.has_next() else None,'Далее →')]:
        if number:
            params=request.GET.copy();params['page']=number;pagination.append({'label':label,'url':'?'+params.urlencode()})
    return render(request,'crm/customers.html',{'filters':filters,'columns':columns,'table_rows':page.object_list,'count':count,'page':page,'pagination':pagination,'sort':sort,'return_query':safe_query(request.GET.urlencode())})

class CustomerEditor(CustomerCardForm):
    version=forms.CharField(required=False,widget=forms.HiddenInput)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk:self.fields['version'].initial=version(self.instance)

@login_required
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
@transaction.atomic
def editor(request,pk=None):
    if not request.user.has_perms(['crm.view_customer','crm.add_customer' if not pk else 'crm.view_customer']):raise PermissionDenied
    if request.method=='POST' and pk and not request.user.has_perm('crm.change_customer'):raise PermissionDenied
    customer=get_object_or_404(Customer.objects.select_for_update(),pk=pk) if pk else Customer()
    before=model_to_dict(customer);current=version(customer) if pk else ''
    form=CustomerEditor(request.POST if request.method=='POST' else None,instance=customer,prefix='customer')
    query=request.POST.get('return_query','') if request.method=='POST' else request.GET.get('return_query','')
    editable=request.user.has_perm('crm.change_customer') if pk else request.user.has_perm('crm.add_customer')
    if not editable:
        for field in form.fields.values():field.disabled=True
    if request.method=='POST' and form.is_valid():
        if pk and form.cleaned_data['version']!=current:form.add_error(None,'Заказчик изменён в другом окне. Обновите страницу и проверьте данные.')
        else:
            saved=form.save();audit(request.user,saved,before,'updated' if pk else 'created')
            Contract.objects.filter(customer=saved).update(updated_at=timezone.now())
            messages.success(request,'Заказчик сохранён. Изменения действуют во всех его договорах.');return redirect(back_url(query))
    contracts=Contract.objects.filter(customer=customer).select_related('operator').order_by('-date','-pk') if pk and request.user.has_perm('crm.view_contract') else Contract.objects.none()
    similar=[]
    if pk:
        if customer.kind=='person':similar=[c for c in customer_matches(model_to_dict(customer))[1] if c.pk!=customer.pk]
        elif customer.inn:similar=list(Customer.objects.filter(kind='company',inn=customer.inn).exclude(pk=customer.pk))
    task_query=Task.objects.filter(Q(customer=customer)|Q(customer__isnull=True,contract__customer=customer)).select_related('contract','employee','task_type').order_by('done','due','pk') if pk and request.user.has_perm('crm.view_task') else Task.objects.none()
    payment_query=Payment.objects.filter(Q(contract__customer=customer)|Q(legacy_payer=customer)).select_related('contract','method','legacy_payer').order_by('-date','-pk') if pk and request.user.has_perm('crm.view_payment') else Payment.objects.none()
    task_page=Paginator(task_query,100).get_page(request.GET.get('task_page'))
    finance_page=Paginator(payment_query,100).get_page(request.GET.get('finance_page'))
    finance_page.object_list=list(finance_page.object_list)
    if finance_page.object_list:
        from .models import payment_operation_choices
        labels=dict(payment_operation_choices())
        for payment in finance_page.object_list:
            payment.display_kind=labels.get(payment.kind,payment.kind)
            payment.incoming=payment.amount if payment.kind in ('customer','operator_refund') else 0
            payment.outgoing=payment.amount if payment.kind in ('operator','customer_refund') else 0
    totals=payment_query.aggregate(incoming=Sum('amount',filter=Q(kind__in=['customer','operator_refund'])),outgoing=Sum('amount',filter=Q(kind__in=['operator','customer_refund'])))
    def page_links(page,key,anchor):
        result=[]
        for number,label in [(page.previous_page_number() if page.has_previous() else None,'← Назад'),(page.next_page_number() if page.has_next() else None,'Далее →')]:
            if number:
                query=request.GET.copy();query[key]=number
                result.append({'label':label,'url':'?'+query.urlencode()+'#'+anchor})
        return result
    return render(request,'crm/customer_editor.html',{'form':form,'customer':customer,'is_new':not pk,'editable':editable,'back_url':back_url(query),'return_query':safe_query(query),'visible_fields':[f for f in form if not f.is_hidden],'contracts':contracts[:100],'contract_count':contracts.count(),'similar':similar[:10],'customer_tasks':task_page,'customer_payments':finance_page,'customer_payment_totals':totals,'task_links':page_links(task_page,'task_page','customer-tasks'),'finance_links':page_links(finance_page,'finance_page','customer-finances')})

@login_required
@permission_required('crm.view_customer',raise_exception=True)
@never_cache
def column_choices(request):
    from django.http import JsonResponse
    key=request.GET.get('column','')
    if key not in dict(COLUMNS):return JsonResponse({'values':[]},status=400)
    form=CustomerFilters(request.GET)
    if not form.is_valid():return JsonResponse({'values':[]})
    query=normalize_location(request.GET.get('choice_search','')[:250])
    values=sorted({cell['filter_value'] for row in matching_rows(form.cleaned_data) for cell in row['cells'] if cell['key']==key and query in normalize_location(cell['filter_value'])},key=normalize_location)
    return JsonResponse({'values':values[:100],'more':len(values)>100})
