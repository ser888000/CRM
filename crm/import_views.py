import secrets
import time
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required,permission_required
from django.db import IntegrityError,OperationalError
from django.shortcuts import render,redirect
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from django.views.decorators.cache import never_cache
from .models import Contract,TaskTemplate
from .services import task_due
from .tourvisor import fetch_order,normalize_order,apply_order,TourvisorError,GROUPS

class LookupForm(forms.Form):
    order_id=forms.RegexField(r'^[0-9]{1,20}$',label='ID онлайн-заявки / номер договора Турвизора',max_length=20)

class ConfirmForm(forms.Form):
    token=forms.CharField(widget=forms.HiddenInput)
    groups=forms.MultipleChoiceField(label='Что перенести / обновить',choices=list(GROUPS.items()),widget=forms.CheckboxSelectMultiple)
    end=forms.DateField(label='Подтвердите дату окончания тура',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    templates=forms.ModelMultipleChoiceField(label='Создать задачи (только для нового договора)',queryset=TaskTemplate.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for t in TaskTemplate.objects.all():
            self.fields[f'due_{t.pk}']=forms.DateField(label=f'Срок: {t.name}',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    def clean(self):
        data=super().clean()
        for t in data.get('templates',[]):
            if not data.get(f'due_{t.pk}'):self.add_error(f'due_{t.pk}','Укажите дату выбранной задачи.')
        return data

@login_required
@permission_required(('crm.add_contract','crm.change_contract','crm.view_contract','crm.add_customer','crm.change_customer','crm.add_tourist','crm.change_tourist','crm.add_operator','crm.add_task'),raise_exception=True)
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def import_order(request):
    lookup=LookupForm(initial={'order_id':request.GET.get('order_id','')})
    preview=None;confirm=None;existing=None;comparison=[]
    if request.method=='POST' and request.POST.get('action')=='cancel':
        request.session.pop('tourvisor_preview',None)
        return redirect('contracts')
    if request.method=='POST' and request.POST.get('action')=='lookup':
        lookup=LookupForm(request.POST)
        request.session.pop('tourvisor_preview',None)
        if lookup.is_valid():
            try:
                raw=fetch_order(lookup.cleaned_data['order_id'])
                existing=Contract.objects.filter(tourvisor_id=str(raw['id'])).first()
                request.session['tourvisor_preview']={'order':raw,'token':secrets.token_urlsafe(24),'created':time.time(),'existing':existing.pk if existing else None,'version':str(existing.updated_at) if existing else None}
            except TourvisorError as e:messages.error(request,str(e))
    stored=request.session.get('tourvisor_preview')
    if stored:
        if time.time()-stored['created']>1800:
            request.session.pop('tourvisor_preview',None)
            messages.error(request,'Предпросмотр устарел. Загрузите заявку повторно.')
        else:
            try:
                preview=normalize_order(stored['order'])
                existing=Contract.objects.filter(pk=stored['existing']).first() if stored['existing'] else None
                default_contract=Contract(**preview['contract'])
                initial={'token':stored['token'],'groups':list(GROUPS) if not existing else [],'end':preview['contract']['end'],'templates':TaskTemplate.objects.filter(active=True) if not existing else []}
                initial.update({f'due_{t.pk}':task_due(default_contract,t) for t in TaskTemplate.objects.all()})
                confirm=ConfirmForm(request.POST if request.method=='POST' and request.POST.get('action')=='confirm' else None,initial=initial)
                if existing:
                    for key,value in preview['contract'].items():
                        if key not in ('number','date','tourvisor_time') and getattr(existing,key)!=value:
                            comparison.append((existing._meta.get_field(key).verbose_name,getattr(existing,key),value))
                    if existing.amount!=preview['price']:comparison.append(('Стоимость',existing.amount,preview['price']))
                    for key,value in preview['customer'].items():
                        current=getattr(existing.customer,key)
                        if current!=value:comparison.append(('Заказчик: '+existing.customer._meta.get_field(key).verbose_name,current,value))
                if request.method=='POST' and request.POST.get('action')=='confirm' and confirm.is_valid():
                    if not secrets.compare_digest(confirm.cleaned_data['token'],stored['token']):
                        raise TourvisorError('Предпросмотр изменился. Загрузите заявку повторно.')
                    if preview['contract']['start'] and confirm.cleaned_data['end']<preview['contract']['start']:
                        raise TourvisorError('Дата окончания тура раньше начала. Проверьте даты.')
                    if stored['existing'] and (not existing or str(existing.updated_at)!=stored['version']):
                        raise TourvisorError('Договор изменился после предпросмотра. Загрузите заявку повторно.')
                    contract=apply_order(stored['order'],request.user,set(confirm.cleaned_data['groups']),
                        templates=confirm.cleaned_data.get('templates'),dates={t.pk:confirm.cleaned_data.get(f'due_{t.pk}') for t in confirm.cleaned_data.get('templates',[])},
                        expected=stored['existing'],expected_version=stored['version'],end=confirm.cleaned_data['end'])
                    request.session.pop('tourvisor_preview',None)
                    messages.success(request,'Договор обновлён.' if existing else 'Договор импортирован.')
                    return redirect('contract_card',pk=contract.pk)
            except TourvisorError as e:messages.error(request,str(e))
            except IntegrityError:messages.error(request,'Договор уже создан другим запросом. Загрузите предпросмотр повторно; дубликат не сохранён.')
            except OperationalError:messages.error(request,'База CRM временно занята. Попробуйте сохранить позже; частичный импорт не сохранён.')
    return render(request,'crm/import.html',{'lookup':lookup,'preview':preview,'confirm':confirm,'existing':existing,'comparison':comparison})
