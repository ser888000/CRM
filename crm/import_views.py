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
from .tourvisor_diff import compare_order,task_moves
from .tourvisor import fetch_order,normalize_order,apply_order,TourvisorError,GROUPS

class LookupForm(forms.Form):
    order_id=forms.RegexField(r'^[0-9]{1,20}$',label='ID онлайн-заявки / номер договора Турвизора',max_length=20)

class ConfirmForm(forms.Form):
    token=forms.CharField(widget=forms.HiddenInput)
    groups=forms.MultipleChoiceField(label='Что перенести / обновить',choices=list(GROUPS.items()),widget=forms.CheckboxSelectMultiple,required=False)
    end=forms.DateField(label='Подтвердите дату окончания тура',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    templates=forms.ModelMultipleChoiceField(label='Создать задачи (только для нового договора)',queryset=TaskTemplate.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    move_tasks=forms.MultipleChoiceField(label='Перенести незавершённые задачи',choices=[],required=False,widget=forms.CheckboxSelectMultiple)
    def __init__(self,*args,moves=None,existing=False,customer_data=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.moves=moves or []
        self.fields['move_tasks'].choices=[(str(m['task'].pk),m['task'].title) for m in self.moves]
        if existing:self.fields['templates'].disabled=True
        elif customer_data:
            from .customer_matching import customer_matches
            match,candidates=customer_matches(customer_data)
            if candidates:
                self.fields['customer_choice']=forms.ChoiceField(label='Заказчик в CRM',choices=[('auto','Использовать совпавшего заказчика: '+str(match))] if match else [('', 'Выберите заказчика')],initial='auto' if match else '')
                self.fields['customer_choice'].choices=list(self.fields['customer_choice'].choices)+[(str(c.pk),f'{c.name} · {c.main_phone} · {c.main_email}') for c in candidates]+[('new','Создать нового заказчика')]

        for move in self.moves:
            self.fields[f'move_due_{move["task"].pk}']=forms.DateField(label=move['task'].title,required=False,initial=move['new'],widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','data-move-anchor':move['anchor'],'data-old-due':move['old'].isoformat(),'data-old-anchor':move['old_anchor'].isoformat()}))
        for t in TaskTemplate.objects.all():
            self.fields[f'due_{t.pk}']=forms.DateField(label=f'Срок: {t.name}',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    def clean(self):
        data=super().clean()
        for t in data.get('templates',[]):
            if not data.get(f'due_{t.pk}'):self.add_error(f'due_{t.pk}','Укажите дату выбранной задачи.')
        for move_id in data.get('move_tasks',[]):
            if not data.get(f'move_due_{move_id}'):self.add_error(f'move_due_{move_id}','Укажите новую дату задачи.')
        if data.get('move_tasks') and 'tour' not in data.get('groups',[]):
            self.add_error('move_tasks','Для переноса задач выберите раздел «Параметры тура».')
        return data

@login_required
@permission_required(('crm.add_contract','crm.change_contract','crm.view_contract','crm.add_customer','crm.change_customer','crm.add_tourist','crm.change_tourist','crm.add_operator','crm.add_task'),raise_exception=True)
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def import_order(request):
    lookup=LookupForm(initial={'order_id':request.GET.get('order_id','')})
    preview=None;confirm=None;existing=None;comparison=[];sections=[];moves=[]
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
                normalized=normalize_order(raw)
                request.session['tourvisor_preview']['task_versions']={str(m['task'].pk):{'due':m['old'].isoformat(),'template':m['task'].template_id,'anchor':m['task'].template.anchor} for m in task_moves(existing,normalized)} if existing else {}
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
                sections=compare_order(existing,preview)
                moves=task_moves(existing,preview) if existing else []
                initial={'token':stored['token'],'groups':list(GROUPS) if not existing else [s['key'] for s in sections if s['changed']],'end':preview['contract']['end'] or (existing.end if existing else None),'templates':TaskTemplate.objects.filter(active=True) if not existing else [],'move_tasks':[str(m['task'].pk) for m in moves]}
                initial.update({f'due_{t.pk}':task_due(default_contract,t) for t in TaskTemplate.objects.all()})
                confirm=ConfirmForm(request.POST if request.method=='POST' and request.POST.get('action')=='confirm' else None,initial=initial,moves=moves,existing=bool(existing),customer_data=preview['customer'])
                selected_groups=confirm['groups'].value() or []
                for section in sections:section['selected']=section['key'] in selected_groups
                selected_moves=confirm['move_tasks'].value() or []
                for move in moves:
                    move['selected']=str(move['task'].pk) in selected_moves
                    move['field']=confirm[f'move_due_{move["task"].pk}']
                if request.method=='POST' and request.POST.get('action')=='confirm' and confirm.is_valid():
                    if not secrets.compare_digest(confirm.cleaned_data['token'],stored['token']):
                        raise TourvisorError('Предпросмотр изменился. Загрузите заявку повторно.')
                    if preview['contract']['start'] and confirm.cleaned_data['end']<preview['contract']['start']:
                        raise TourvisorError('Дата окончания тура раньше начала. Проверьте даты.')
                    if stored['existing'] and (not existing or str(existing.updated_at)!=stored['version']):
                        raise TourvisorError('Договор изменился после предпросмотра. Загрузите заявку повторно.')
                    if confirm.cleaned_data['move_tasks'] and not request.user.has_perm('crm.change_task'):
                        raise TourvisorError('Недостаточно прав для переноса задач.')
                    if existing and not confirm.cleaned_data['groups'] and not confirm.cleaned_data['move_tasks']:
                        request.session.pop('tourvisor_preview',None)
                        messages.info(request,'Изменения не выбраны. Договор сохранён без изменений.')
                        return redirect('contract_card',pk=existing.pk)
                    updates=[]
                    for move in moves:
                        key=str(move['task'].pk)
                        if key in confirm.cleaned_data['move_tasks']:
                            version=stored.get('task_versions',{}).get(key)
                            if not version:raise TourvisorError('Состав задач изменился. Загрузите сверку повторно.')
                            updates.append({'id':move['task'].pk,'old':version['due'],'template':version['template'],'anchor':version.get('anchor'),'new':confirm.cleaned_data[f'move_due_{key}']})
                    contract=apply_order(stored['order'],request.user,set(confirm.cleaned_data['groups']),
                        templates=confirm.cleaned_data.get('templates'),dates={t.pk:confirm.cleaned_data.get(f'due_{t.pk}') for t in confirm.cleaned_data.get('templates',[])},
                        expected=stored['existing'],expected_version=stored['version'],end=confirm.cleaned_data['end'],task_updates=updates,customer_choice=confirm.cleaned_data.get('customer_choice','auto'))
                    request.session.pop('tourvisor_preview',None)
                    messages.success(request,'Договор обновлён.' if existing else 'Договор импортирован.')
                    return redirect('contract_card',pk=contract.pk)
            except TourvisorError as e:messages.error(request,str(e))
            except IntegrityError:messages.error(request,'Договор уже создан другим запросом. Загрузите предпросмотр повторно; дубликат не сохранён.')
            except OperationalError:messages.error(request,'База CRM временно занята. Попробуйте сохранить позже; частичный импорт не сохранён.')
    return render(request,'crm/import.html',{'lookup':lookup,'preview':preview,'confirm':confirm,'existing':existing,'comparison':comparison,'sections':sections,'moves':moves,'changed_count':sum(s['changed'] for s in sections)})
