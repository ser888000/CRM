"""Owner-scoped preview and one-transaction-per-order batch creation."""
from datetime import timedelta,date
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required,permission_required
from django.db import transaction,IntegrityError,OperationalError
from django.http import JsonResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from django.views.decorators.http import require_POST
from .models import TourvisorBatch,TourvisorBatchRow,Contract,TaskTemplate
from .tourvisor import fetch_orders,normalize_order,apply_order,TourvisorError,GROUPS,check_import_boundary
from .tourvisor_diff import compare_order
from .customer_matching import customer_matches
from .services import task_due

PERMISSIONS=('crm.add_contract','crm.change_contract','crm.view_contract','crm.add_customer','crm.change_customer','crm.add_tourist','crm.change_tourist','crm.add_operator','crm.add_task')

class BatchLookupForm(forms.Form):
    limit=forms.TypedChoiceField(label='Последние онлайн-заявки',choices=[(25,'25 заявок'),(50,'50 заявок'),(100,'100 заявок')],coerce=int,initial=25)
    lastid=forms.RegexField(r'^[0-9]{1,20}$',label='Только ID больше указанного',required=False,max_length=20,help_text='Необязательно. Это ID заявки Турвизора, а не внутренний номер CRM.')


def summarize(row):
    info={'row':row,'existing':row.contract,'eligible':False,'normalized':None,'status':'Ошибка','error':row.message}
    if row.state=='done':info.update(status='Создан',error='');return info
    try:
        n=normalize_order(row.payload);info['normalized']=n
        existing=Contract.objects.filter(tourvisor_id=row.source_id).select_related('customer','operator').first()
        if existing:
            changed=any(s['changed'] for s in compare_order(existing,n))
            info.update(existing=existing,status='Есть изменения' if changed else 'Уже загружен',error='')
        elif Contract.objects.filter(number=row.source_id).exists():
            info['existing']=Contract.objects.filter(number=row.source_id).first()
            info['error']='В CRM есть ручной договор с этим номером. Проверьте его перед импортом.'
        else:
            check_import_boundary(row.source_id)
            match,candidates=customer_matches(n['customer'])
            info.update(eligible=True,status='Новая',match=match,candidates=candidates,error=row.message if row.state=='error' else '')
    except TourvisorError as e:info['error']=str(e)
    return info


class BatchPlanForm(forms.Form):
    selected=forms.MultipleChoiceField(choices=[],required=True,error_messages={'required':'Выберите хотя бы одну новую заявку.'})
    templates=forms.ModelMultipleChoiceField(label='Задачи новых договоров',queryset=TaskTemplate.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    def __init__(self,*args,infos,**kwargs):
        super().__init__(*args,**kwargs);self.infos={str(i['row'].pk):i for i in infos if i['eligible']}
        self.fields['selected'].choices=[(key,info['row'].source_id) for key,info in self.infos.items()]
        self.fields['templates'].initial=TaskTemplate.objects.filter(active=True)
        self.task_templates=list(TaskTemplate.objects.all())
        for key,info in self.infos.items():
            n=info['normalized'];plan=info['row'].plan
            end=plan.get('end') or n['contract']['end']
            self.fields['end_'+key]=forms.DateField(required=False,initial=end,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','data-batch-end':key}))
            choices=[('auto','Новый заказчик — совпадений нет')]
            if info['candidates']:
                choices=([('auto','Совпал: '+str(info['match']))] if info['match'] else [('', 'Выберите заказчика')])
                choices += [(str(c.pk),f'{c.name} · {c.main_phone} · {c.main_email}') for c in info['candidates']]+[('new','Создать нового заказчика')]
            self.fields['customer_'+key]=forms.ChoiceField(required=False,choices=choices,initial=plan.get('customer_choice','auto' if info.get('match') or not info['candidates'] else ''))
            default=Contract(**n['contract'])
            if isinstance(end,str):
                try:default.end=date.fromisoformat(end)
                except ValueError:pass
            for t in self.task_templates:
                initial=plan.get('dates',{}).get(str(t.pk)) or task_due(default,t)
                self.fields[f'due_{key}_{t.pk}']=forms.DateField(required=False,initial=initial,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','data-batch-row':key,'data-task-anchor':t.anchor,'data-task-offset':t.offset,'data-created':default.date.isoformat(),'data-start':default.start.isoformat() if default.start else ''}))
    def clean(self):
        data=super().clean();plans={}
        for key in data.get('selected',[]):
            info=self.infos[key];n=info['normalized'];end=data.get('end_'+key);choice=data.get('customer_'+key)
            if not end:self.add_error('end_'+key,'Подтвердите дату окончания тура.');continue
            if n['contract']['start'] and end<n['contract']['start']:self.add_error('end_'+key,'Окончание раньше начала тура.');continue
            if not choice:self.add_error('customer_'+key,'Выберите существующего заказчика или создание нового.');continue
            c=Contract(**{**n['contract'],'end':end});dates={}
            for t in data.get('templates',[]):
                due=data.get(f'due_{key}_{t.pk}') or task_due(c,t)
                if due is None:self.add_error(f'due_{key}_{t.pk}','Не удалось определить срок задачи. Укажите дату.');continue
                dates[str(t.pk)]=due.isoformat()
            plans[key]={'end':end.isoformat(),'customer_choice':choice,'templates':[t.pk for t in data.get('templates',[])],'dates':dates}
        data['plans']=plans
        return data


def expire(batch):
    if batch.expires_at>timezone.now():return False
    batch.rows.exclude(payload={}).update(payload={},plan={})
    return True

@login_required
@permission_required(PERMISSIONS,raise_exception=True)
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def batch_list(request):
    lookup=BatchLookupForm(request.POST if request.method=='POST' else None)
    if request.method=='POST' and lookup.is_valid():
        try:
            entries=fetch_orders(**lookup.cleaned_data)
            if not entries:messages.info(request,'По этому запросу онлайн-заявок нет.')
            else:
                with transaction.atomic():
                    batch=TourvisorBatch.objects.create(owner=request.user,expires_at=timezone.now()+timedelta(minutes=30))
                    TourvisorBatchRow.objects.bulk_create([TourvisorBatchRow(batch=batch,source_id=str(o['id']),payload=o) for o in entries])
                return redirect('tourvisor_batch_detail',pk=batch.pk)
        except TourvisorError as e:messages.error(request,str(e))
        except (IntegrityError,OperationalError):messages.error(request,'База CRM временно занята. Повторите загрузку списка.')
    batches=TourvisorBatch.objects.filter(owner=request.user,expires_at__gt=timezone.now()).order_by('-created_at')[:5]
    return render(request,'crm/batch.html',{'lookup':lookup,'batches':batches})

@login_required
@permission_required(PERMISSIONS,raise_exception=True)
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def batch_detail(request,pk):
    batch=get_object_or_404(TourvisorBatch,pk=pk,owner=request.user)
    expired=expire(batch);infos=[];plan=None
    if not expired:
        infos=[summarize(row) for row in batch.rows.select_related('contract__customer','contract__operator')]
        plan=BatchPlanForm(request.POST if request.method=='POST' else None,infos=infos)
        if request.method=='POST':
            if batch.state=='running':messages.error(request,'Загрузка уже начата. Продолжите очередь или дождитесь её завершения.')
            elif plan.is_valid():
                with transaction.atomic():
                    locked=TourvisorBatch.objects.select_for_update().get(pk=batch.pk)
                    if locked.state=='running':messages.error(request,'Эта очередь уже запущена в другом окне.')
                    elif locked.expires_at<=timezone.now():messages.error(request,'Предпросмотр устарел. Загрузите список повторно.')
                    else:
                        for key,rowplan in plan.cleaned_data['plans'].items():
                            locked.rows.filter(pk=int(key)).exclude(state='done').update(plan=rowplan,state='queued',message='')
                        locked.state='running';locked.save(update_fields=['state'])
                        return redirect(reverse('tourvisor_batch_detail',args=[batch.pk])+'?run=1')
        for info in infos:
            key=str(info['row'].pk)
            if info['eligible']:
                info['end_field']=plan['end_'+key];info['customer_field']=plan['customer_'+key]
                info['selected']=key in (plan['selected'].value() or [])
                info['task_fields']=[{'name':t.name,'field':plan[f'due_{key}_{t.pk}']} for t in plan.task_templates]
    counts={state:batch.rows.filter(state=state).count() for state in ('done','error','queued')}
    return render(request,'crm/batch.html',{'batch':batch,'infos':infos,'plan':plan,'counts':counts,'expired':expired,'can_start':any(info['eligible'] for info in infos),'auto_run':request.GET.get('run')=='1' and batch.state=='running'})

@login_required
@permission_required(PERMISSIONS,raise_exception=True)
@require_POST
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def batch_step(request,pk):
    batch=get_object_or_404(TourvisorBatch,pk=pk,owner=request.user)
    if expire(batch):return JsonResponse({'error':'Предпросмотр устарел. Загрузите список повторно.'},status=410)
    try:
        with transaction.atomic():
            locked=TourvisorBatch.objects.select_for_update().get(pk=batch.pk)
            if locked.expires_at<=timezone.now():return JsonResponse({'error':'Предпросмотр устарел. Загрузите список повторно.'},status=410)
            if locked.state!='running':return JsonResponse({'error':'Очередь не запущена.'},status=409)
            row=locked.rows.select_for_update().filter(state='queued').first()
            if row:
                try:
                    if Contract.objects.filter(tourvisor_id=row.source_id).exists():
                        row.contract=Contract.objects.get(tourvisor_id=row.source_id)
                        row.state='done';row.message='Уже создан — повторно не импортирован.'
                    else:
                        task_ids=row.plan['templates'];templates=list(TaskTemplate.objects.filter(pk__in=task_ids))
                        if len(templates)!=len(task_ids):raise TourvisorError('Шаблоны задач изменились. Проверьте выбор задач перед повтором.')
                        row.contract=apply_order(row.payload,request.user,set(GROUPS),templates=templates,
                            dates={int(key):date.fromisoformat(value) for key,value in row.plan['dates'].items()},
                            end=date.fromisoformat(row.plan['end']),customer_choice=row.plan['customer_choice'])
                        row.state='done';row.message='Договор создан.'
                    row.payload={};row.plan={}
                except (TourvisorError,IntegrityError) as e:
                    row.state='error';row.message=str(e) if isinstance(e,TourvisorError) else 'Договор уже создаётся другим запросом. Проверьте результат перед повтором.'
                row.save(update_fields=['state','message','contract','payload','plan'])
            counts={s:locked.rows.filter(state=s).count() for s in ('done','error','queued')}
            finished=counts['queued']==0
            if finished:locked.state='finished';locked.save(update_fields=['state'])
            return JsonResponse({'finished':finished,'counts':counts,'row':{'id':row.pk,'state':row.state,'message':row.message,'url':reverse('contract_card',args=[row.contract_id]) if row.contract_id else ''} if row else None})
    except OperationalError:return JsonResponse({'error':'База CRM временно занята. Возобновите очередь через несколько секунд.'},status=409)
