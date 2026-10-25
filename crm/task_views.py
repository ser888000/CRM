"""Daily task journal, editor and explicit bulk actions."""
from datetime import timedelta
import hashlib
import json
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required,permission_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms.models import model_to_dict
from django.http import QueryDict
from django.core.paginator import Paginator
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from .models import Task,Customer,Contract,Operator,TaskTemplate,TaskType,AuditEvent,normalize_location
from .reference_defaults import apply_reference_defaults
from .widgets import LocationInput
from .services import repeat_tasks

PERIODS=[('today','Сегодня'),('tomorrow','Завтра')]
STATUSES=[('all','Все'),('planned','Запланировано'),('done','Выполнено'),('overdue','Просрочено')]
COLUMNS=[('title','Задача и описание'),('due','Срок'),('customer','Заказчик / договор'),('operator','ТО / брони'),('employee','Сотрудник'),('status','Статус')]
PARAMS={'period','status','start','end','q','customer','operator','employee','page','sort'}|{'f_'+key for key,_ in COLUMNS}

def safe_query(value):
    data=QueryDict(value[:4000]).copy()
    for key in list(data):
        if key not in PARAMS:del data[key]
    return data.urlencode()

def back_url(value):
    query=safe_query(value)
    return '/tasks/'+('?' +query if query else '')

def version(task):
    return hashlib.sha256(json.dumps(model_to_dict(task),default=str,sort_keys=True).encode()).hexdigest()

class TaskFilters(forms.Form):
    q=forms.CharField(label='Задача, описание или бронь',required=False,max_length=250)
    customer=forms.CharField(label='Заказчик',required=False,max_length=250)
    operator=forms.CharField(label='Туроператор',required=False,max_length=200)
    employee=forms.ChoiceField(label='Сотрудник',required=False,choices=[])
    start=forms.DateField(label='Срок с',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='по',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.order_fields(['q','customer','operator','employee','start','end'])
        self.fields['employee'].choices=[('','Все сотрудники'),('shared','Общие задачи')]+[(str(u.pk),u.get_full_name() or u.username) for u in get_user_model().objects.filter(is_active=True)]
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['end']<data['start']:self.add_error('end','Окончание периода раньше начала.')
        return data

@login_required
@permission_required('crm.view_task',raise_exception=True)
@never_cache
def journal(request):
    if 'reset' in request.GET:
        request.session.pop('task_journal',None);return redirect('tasks')
    if not request.GET and request.session.get('task_journal'):return redirect(back_url(request.session['task_journal']))
    today=timezone.localdate();mode=request.GET.get('period','today')
    legacy_status=mode if mode in ('planned','done') else 'all'
    if mode in ('planned','done'):mode='all'
    if mode not in ('today','tomorrow','overdue','custom','all'):mode='today'
    status='overdue' if mode=='overdue' else request.GET.get('status',legacy_status)
    if status not in dict(STATUSES):status='all'
    params=request.GET.copy()
    if mode in ('today','tomorrow'):
        day=today+timedelta(days=mode=='tomorrow');params['start']=params['end']=day.isoformat()
    filters=TaskFilters(params)
    tasks=list(Task.objects.select_related('task_type','customer','contract__customer','contract__operator','operator','employee').prefetch_related('contract__bookings').order_by('done','due','pk'))
    if filters.is_valid():
        data=filters.cleaned_data
        def matches(t):
            customer=t.customer or (t.contract.customer if t.contract_id else None)
            values={'q':' '.join([t.display_title,t.description,t.booking_number,*[n for n,_ in t.booking_entries]]),'customer':str(customer or ''),'operator':str(t.tour_operator or '')}
            if any(normalize_location(data[k]) not in normalize_location(values[k]) for k in values if data.get(k)):return False
            if data['employee']=='shared' and t.employee_id:return False
            if data['employee'] not in ('','shared') and str(t.employee_id)!=data['employee']:return False
            return True
        tasks=[t for t in tasks if matches(t)]
        request.session['task_journal']=safe_query(request.GET.urlencode())
    else:data={}
    def in_period(t,key):
        if key=='overdue':return not t.done and t.due<today
        if key=='today':return t.due==today
        if key=='tomorrow':return t.due==today+timedelta(days=1)
        return not ((data.get('start') and t.due<data['start']) or (data.get('end') and t.due>data['end']))
    def in_status(t,key):return key=='all' or t.done==(key=='done')
    for t in tasks:
        t.display_customer=t.customer or (t.contract.customer if t.contract_id else None)
        t.column_values={'title':t.display_title,'due':t.due.strftime('%d.%m.%Y'),'customer':str(t.display_customer or '—')+(' / '+str(t.contract) if t.contract_id else ''),'operator':' / '.join([str(t.tour_operator or '—'),*[n for n,_ in t.booking_entries]]),'employee':(t.employee.get_full_name() or t.employee.username) if t.employee else 'Общая задача','status':'Выполнено' if t.done else 'Запланировано'}
    columns=[]
    for key,label in COLUMNS:
        selected=request.GET.getlist('f_'+key)
        choices=sorted({t.column_values[key] for t in tasks}|set(selected),key=normalize_location)
        columns.append({'key':key,'label':label,'options':[{'value':v,'selected':v in selected} for v in choices],'active':bool(selected),'direction':'↑' if request.GET.get('sort')==key else '↓' if request.GET.get('sort')=='-'+key else '', 'sort':('-' if request.GET.get('sort')==key else '')+key})
    tasks=[t for t in tasks if all(not request.GET.getlist('f_'+key) or t.column_values[key] in request.GET.getlist('f_'+key) for key,_ in COLUMNS)]
    tabs=[];status_tabs=[]
    for key,label in PERIODS:
        query=request.GET.copy();query.pop('page',None);query['period']=key
        if key in ('today','tomorrow'):query['status']='all'
        tabs.append({'key':key,'label':label,'count':sum(in_period(t,key) for t in tasks),'url':'?'+query.urlencode()})
    period_tasks=[t for t in tasks if in_period(t,mode)]
    for key,label in STATUSES:
        query=request.GET.copy();query.pop('page',None);query['status']=key
        if mode=='overdue':query['period']='custom'
        status_tabs.append({'key':key,'label':label,'count':sum(not t.done and t.due<today for t in tasks) if key=='overdue' else sum(in_status(t,key) for t in period_tasks),'url':'?'+query.urlencode()})
    rows=[t for t in tasks if not t.done and t.due<today] if status=='overdue' else [t for t in period_tasks if in_status(t,status)]
    sort=request.GET.get('sort','');key=sort.lstrip('-')
    if key in dict(COLUMNS):rows.sort(key=lambda t:t.due if key=='due' else normalize_location(t.column_values[key]),reverse=sort.startswith('-'))
    total=len(rows);page=Paginator(rows,100).get_page(request.GET.get('page'));rows=list(page.object_list)
    pagination=[]
    for number,label in [(page.previous_page_number() if page.has_previous() else None,'← Назад'),(page.next_page_number() if page.has_next() else None,'Далее →')]:
        if number:
            query=request.GET.copy();query['page']=number;pagination.append({'label':label,'url':'?'+query.urlencode()})
    for t in rows:t.overdue=not t.done and t.due<today
    return render(request,'crm/tasks.html',{'rows':rows,'filters':filters,'period':mode,'status':status,'tabs':tabs,'status_tabs':status_tabs,'columns':columns,'sort':sort,'today':today,'return_query':safe_query(request.GET.urlencode()),'count':total,'page':page,'pagination':pagination})

class TaskEditorForm(forms.ModelForm):
    version=forms.CharField(required=False,widget=forms.HiddenInput)
    repeat=forms.ChoiceField(label='Повтор',required=False,choices=[('','Без повтора'),('day','Каждый день'),('week','Каждую неделю'),('month','Каждый месяц'),('year','Каждый год')])
    occurrences=forms.IntegerField(label='Всего задач, включая первую',min_value=1,max_value=366,initial=1,required=False,help_text='Все повторы создаются сразу, максимум 366.')
    class Meta:
        model=Task
        fields=['task_type','title','description','due','customer','contract','operator','booking_number','employee','done']
        widgets={'title':LocationInput(TaskType),'due':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'description':forms.Textarea(attrs={'rows':3})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['title'].required=False
        self.fields['title'].help_text='Можно выбрать тип задачи или ввести своё название.'
        self.fields['contract'].queryset=Contract.objects.select_related('customer').order_by('-date','-pk')
        self.fields['contract'].label_from_instance=lambda c:f'{c} · {c.customer}'
        self.fields['customer'].label='Заказчик (необязательно)'
        self.fields['contract'].label='Договор (необязательно)'
        self.fields['operator'].help_text='Для задачи без договора. В задаче по договору ТО определяется автоматически.'
        if self.instance.origin_key:
            self.fields['contract'].disabled=True
            self.fields['contract'].help_text='Задача создана по шаблону этого договора; связь закреплена.'
            self.fields['customer'].disabled=True
        if self.instance.pk:
            self.fields['version'].initial=version(self.instance);self.fields.pop('repeat');self.fields.pop('occurrences')
        else:self.fields['due'].initial=timezone.localdate()
        apply_reference_defaults(self,kwargs.get('initial'))
    def clean(self):
        data=super().clean()
        if data.get('task_type'):
            data['title']=data['task_type'].name
            if not data.get('description'):data['description']=data['task_type'].description
        contract=data.get('contract');customer=data.get('customer')
        if contract:
            if customer and customer.pk!=contract.customer_id:self.add_error('customer','Заказчик не соответствует выбранному договору.')
            else:data['customer']=contract.customer
            data['operator']=None
        if not data.get('title'):self.add_error('title','Выберите тип или введите название задачи.')
        if data.get('repeat') and not data.get('occurrences'):self.add_error('occurrences','Укажите число задач.')
        if data.get('repeat') and data.get('done'):self.add_error('done','Для повторяющихся задач оставьте статус «Запланировано».')
        return data

@login_required
@never_cache
@transaction.atomic
def editor(request,pk=None):
    if not request.user.has_perms(['crm.view_task','crm.change_task' if pk else 'crm.add_task']):raise PermissionDenied
    task=get_object_or_404(Task.objects.select_for_update(),pk=pk) if pk else Task()
    before=model_to_dict(task);current_version=version(task) if pk else ''
    form=TaskEditorForm(request.POST if request.method=='POST' else None,instance=task)
    query=request.POST.get('return_query','') if request.method=='POST' else request.GET.get('return_query','')
    if request.method=='POST' and form.is_valid():
        if pk and form.cleaned_data['version']!=current_version:form.add_error(None,'Задача изменена в другом окне. Обновите страницу и проверьте данные.')
        else:
            try:
                with transaction.atomic():
                    saved=form.save();copies=repeat_tasks(saved,form.cleaned_data['repeat'],form.cleaned_data['occurrences']) if not pk and form.cleaned_data.get('repeat') else []
                    changes={key:{'old':str(before.get(key)),'new':str(value)} for key,value in model_to_dict(saved).items() if before.get(key)!=value}
                    AuditEvent.objects.create(actor=request.user,object_type='crm.Task',object_id=str(saved.pk),action='updated' if pk else 'created',changes=changes)
                    for copy in copies:AuditEvent.objects.create(actor=request.user,object_type='crm.Task',object_id=str(copy.pk),action='created_repeat')
                    ids={value for value in (before.get('contract'),saved.contract_id) if value}
                    Contract.objects.filter(pk__in=ids).update(updated_at=timezone.now())
                messages.success(request,f'Создано задач: {1+len(copies)}.' if not pk else 'Задача сохранена.')
                return redirect(back_url(query))
            except (OverflowError,ValueError):form.add_error('due','Повторы выходят за допустимые даты. Уменьшите количество или измените срок.')
    return render(request,'crm/task_editor.html',{'form':form,'task':task,'is_new':not pk,'back_url':back_url(query),'return_query':safe_query(query),'visible_fields':[field for field in form if not field.is_hidden]})

@login_required
@permission_required(('crm.view_task','crm.change_task'),raise_exception=True)
@require_POST
@transaction.atomic
def actions(request):
    target=back_url(request.POST.get('return_query',''));action=request.POST.get('action')
    try:
        raw=request.POST.getlist('tasks')
        if not 1<=len(raw)<=500 or any(not v.isdecimal() or len(v)>18 for v in raw):raise ValueError
        ids={int(v) for v in raw}
        if action not in ('complete','reopen','reschedule','tomorrow'):raise ValueError
        due=forms.DateField().clean(request.POST.get('due')) if action=='reschedule' else None
    except (ValueError,forms.ValidationError):
        messages.error(request,'Выберите задачи и действие. Для переноса укажите дату.');return redirect(target)
    if action=='tomorrow':due=timezone.localdate()+timedelta(days=1)
    count=0;skipped=0;contracts=set()
    for task in Task.objects.select_for_update().filter(pk__in=ids):
        if action in ('reschedule','tomorrow'):
            if task.done:skipped+=1;continue
            field='due';new=due
        else:field='done';new=action=='complete'
        old=getattr(task,field)
        if old==new:continue
        setattr(task,field,new);task.save(update_fields=[field]);count+=1
        if task.contract_id:contracts.add(task.contract_id)
        AuditEvent.objects.create(actor=request.user,object_type='crm.Task',object_id=str(task.pk),action='rescheduled' if field=='due' else 'completed' if new else 'reopened',changes={field:{'old':str(old),'new':str(new)}})
    Contract.objects.filter(pk__in=contracts).update(updated_at=timezone.now())
    messages.success(request,f'Изменено задач: {count}.'+(f' Выполненные задачи пропущены: {skipped}.' if skipped else ''))
    return redirect(target)
