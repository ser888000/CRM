"""Financial journal: filters and totals share the same set of operations."""
from datetime import timedelta
from decimal import Decimal
import hashlib
import json
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required,permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import JsonResponse,QueryDict
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from .models import Payment,PaymentMethod,Contract,AuditEvent,payment_operation_choices,normalize_location
from .forms import PaymentForm
from .templatetags.money import money

COLUMNS=[('date','Дата'),('customer','Заказчик'),('number','Договор'),('operator','ТО'),('kind','Операция'),('incoming','Поступление, ₽'),('outgoing','Расход, ₽'),('method','Способ оплаты'),('currency','Валюта ТО'),('rate','Курс'),('notes','Примечание')]
PARAMS={'customer','number','operator','method','kind','start','end','sort','page','period'}|{'f_'+key for key,_ in COLUMNS}

def safe_query(value):
    data=QueryDict(value[:8000]).copy()
    for key in list(data):
        if key not in PARAMS:del data[key]
    return data.urlencode()

def back_url(query):
    clean=safe_query(query)
    return '/finances/'+('?' +clean if clean else '')

def version(payment):
    return hashlib.sha256(json.dumps(model_to_dict(payment),sort_keys=True,default=str).encode()).hexdigest()

class FinanceFilters(forms.Form):
    customer=forms.CharField(label='Заказчик',required=False,max_length=250)
    number=forms.CharField(label='Номер договора',required=False,max_length=100)
    operator=forms.CharField(label='Туроператор',required=False,max_length=200)
    method=forms.ChoiceField(label='Способ оплаты',required=False)
    kind=forms.ChoiceField(label='Операция',required=False)
    start=forms.DateField(label='Дата с',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='по',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        # Names preserve existing bookmarked filters while supporting directory ordering.
        self.fields['method'].choices=[('','Все способы оплаты')]+[(m.name,m.name) for m in PaymentMethod.objects.all()]
        self.fields['kind'].choices=[('','Все операции')]+payment_operation_choices()
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['start']>data['end']:self.add_error('end','Окончание периода раньше начала.')
        return data

@login_required
@permission_required('crm.view_payment',raise_exception=True)
@never_cache
def journal(request):
    from .journal_period import prepare
    saved=request.session.get('finance_journal','')
    params=prepare(request.GET,saved)
    if 'reset' in request.GET or not request.GET and saved:
        source=params if 'reset' in request.GET else prepare(QueryDict(saved))
        return redirect(back_url(source.urlencode()))
    filters=FinanceFilters(params);rows=[];labels=dict(payment_operation_choices())
    if filters.is_valid():
        data=filters.cleaned_data
        payments=Payment.objects.select_related('contract__customer','contract__operator','method').order_by('-date','-pk')
        if data['start']:payments=payments.filter(date__gte=data['start'])
        if data['end']:payments=payments.filter(date__lte=data['end'])
        if data['kind']:payments=payments.filter(kind=data['kind'])
        if data['method']:payments=payments.filter(method__name=data['method'])
        for payment in payments:
            fields={'customer':str(payment.contract.customer),'number':str(payment.contract),'operator':str(payment.contract.operator)}
            if any(normalize_location(data[key]) not in normalize_location(value) for key,value in fields.items() if data[key]):continue
            payment.incoming=payment.amount if payment.kind in ('customer','operator_refund') else Decimal('0')
            payment.outgoing=payment.amount if payment.kind in ('operator','customer_refund') else Decimal('0')
            values={**fields,'date':payment.date,'kind':labels.get(payment.kind,payment.kind),'incoming':payment.incoming,'outgoing':payment.outgoing,'method':str(payment.method),'currency':payment.currency,'rate':payment.rate,'notes':payment.notes}
            cells=[]
            for key,_ in COLUMNS:
                value=values[key]
                text=money(value) if key in ('incoming','outgoing') or key=='rate' and value is not None else value.strftime('%d.%m.%Y') if key=='date' else str(value) if value is not None else ''
                cells.append({'key':key,'text':text,'filter_value':text or '—'})
            rows.append({'payment':payment,'values':values,'cells':cells})
        request.session['finance_journal']=safe_query(params.urlencode())
    columns=[]
    for i,(key,label) in enumerate(COLUMNS):
        selected=params.getlist('f_'+key)
        options=sorted({row['cells'][i]['filter_value'] for row in rows}|set(selected),key=normalize_location)
        columns.append({'key':key,'label':label,'options':[{'value':v,'selected':v in selected} for v in options],'active':bool(selected),'direction':'↑' if params.get('sort')==key else '↓' if params.get('sort')=='-'+key else '', 'sort':('-' if params.get('sort')==key else '')+key})
    rows=[row for row in rows if all(not params.getlist('f_'+cell['key']) or cell['filter_value'] in params.getlist('f_'+cell['key']) for cell in row['cells'])]
    sort=params.get('sort','');key=sort.lstrip('-')
    if key in dict(COLUMNS):
        present=[r for r in rows if r['values'][key] is not None];missing=[r for r in rows if r['values'][key] is None]
        present.sort(key=lambda r:normalize_location(r['values'][key]) if isinstance(r['values'][key],str) else r['values'][key],reverse=sort.startswith('-'));rows=present+missing
    count=len(rows);incoming=sum((r['payment'].incoming for r in rows),Decimal('0'));outgoing=sum((r['payment'].outgoing for r in rows),Decimal('0'))
    page=Paginator(rows,100).get_page(params.get('page'));pagination=[]
    for number,label in [(page.previous_page_number() if page.has_previous() else None,'← Назад'),(page.next_page_number() if page.has_next() else None,'Далее →')]:
        if number:
            query=params.copy();query['page']=number;pagination.append({'label':label,'url':'?'+query.urlencode()})
    footer=[{'key':key,'text':money(incoming) if key=='incoming' else money(outgoing) if key=='outgoing' else f'ИТОГО: {count}' if key=='date' else ''} for key,_ in COLUMNS]
    return render(request,'crm/finances.html',{'filters':filters,'dateform':filters,'columns':columns,'table_rows':page.object_list,'rows':[r['payment'] for r in page.object_list],'count':count,'incoming':incoming,'outgoing':outgoing,'balance':incoming-outgoing,'footer':footer,'sort':sort,'period':params['period'],'start_value':params['start'],'end_value':params['end'],'page':page,'pagination':pagination,'return_query':safe_query(params.urlencode())})

class FinanceEditor(PaymentForm):
    version=forms.CharField(required=False,widget=forms.HiddenInput)
    class Meta(PaymentForm.Meta):
        fields=['customer','contract','date','kind','method','amount','currency','rate','notes']
        widgets={**PaymentForm.Meta.widgets,'date':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'notes':forms.Textarea(attrs={'rows':3})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['contract'].widget.attrs['data-contracts-url']='/finances/contracts/'
        if self.instance.pk:self.fields['version'].initial=version(self.instance)
    class Media:
        js=['crm/payment_customer.js?v=20261025finance']

@login_required
@never_cache
@sensitive_post_parameters()
@transaction.atomic
def editor(request,pk=None):
    if not request.user.has_perms(['crm.view_payment','crm.change_payment' if pk else 'crm.add_payment']):raise PermissionDenied
    payment=get_object_or_404(Payment.objects.select_for_update(),pk=pk) if pk else Payment()
    before=model_to_dict(payment);current=version(payment) if pk else ''
    initial={}
    if not pk and request.method=='GET' and request.GET.get('copy_from'):
        source_id=request.GET['copy_from']
        if not source_id.isdecimal() or len(source_id)>18:
            from django.http import Http404
            raise Http404
        source=get_object_or_404(Payment.objects.select_related('contract'),pk=source_id)
        initial={key:getattr(source,key) for key in ('contract','kind','amount','method','currency')}
        initial.update(customer=source.contract.customer_id,date=timezone.localdate(),notes='',rate=None)
    form=FinanceEditor(request.POST if request.method=='POST' else None,instance=payment,initial=initial)
    query=request.POST.get('return_query','') if request.method=='POST' else request.GET.get('return_query','')
    if request.method=='POST' and form.is_valid():
        if pk and form.cleaned_data['version']!=current:form.add_error(None,'Операция изменена в другом окне. Обновите страницу и проверьте данные.')
        else:
            saved=form.save()
            changes={key:{'old':str(before.get(key)),'new':str(value)} for key,value in model_to_dict(saved).items() if before.get(key)!=value}
            AuditEvent.objects.create(actor=request.user,object_type='crm.Payment',object_id=str(saved.pk),action='updated' if pk else 'created',changes=changes)
            Contract.objects.filter(pk__in={value for value in (before.get('contract'),saved.contract_id) if value}).update(updated_at=timezone.now())
            messages.success(request,'Финансовая операция сохранена.');return redirect(back_url(query))
    return render(request,'crm/finance_editor.html',{'form':form,'payment':payment,'is_new':not pk,'return_query':safe_query(query),'back_url':back_url(query),'visible_fields':[field for field in form if not field.is_hidden]})

@login_required
@permission_required('crm.view_payment',raise_exception=True)
@never_cache
def contracts_for_customer(request):
    if not request.user.has_perm('crm.add_payment') and not request.user.has_perm('crm.change_payment'):raise PermissionDenied
    qs=Contract.objects.select_related('customer').order_by('-date','-pk');customer=request.GET.get('customer','')
    if customer:
        if not customer.isdecimal() or len(customer)>18:return JsonResponse({'contracts':[]})
        qs=qs.filter(customer_id=customer)
    return JsonResponse({'contracts':[{'id':c.pk,'label':f'{c} · {c.customer}'} for c in qs]})
