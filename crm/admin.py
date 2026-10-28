from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.urls import path
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html
from .models import Customer, Operator, Tourist, Contract, Booking, ContractLine, Payment, Task, TaskTemplate, AuditEvent, ContractType, PaymentMethod, DepartureCity, Country, Currency, Meal, Transfer, Insurance, FuelSurcharge
from .services import create_tasks, create_contract_tasks, contract_task_schedule, copy_contract
from .forms import ContractForm, PaymentForm
from .templatetags.money import money
from .widgets import MoneyInput
from django.db import models
from django.db.models import Sum,Q
from django.utils.html import format_html_join

class AuditedAdmin(admin.ModelAdmin):
    def __init__(self,model,admin_site):
        super().__init__(model,admin_site)
        if hasattr(model,'is_hidden'):
            self.list_display=tuple(self.list_display)+('is_hidden',)
            self.list_editable=tuple(self.list_editable)+('is_hidden',)

    class Media:
        css={'all':['crm/numeric_tables.css']}
        js=['crm/numeric_tables.js']
    formfield_overrides={models.DecimalField:{'localize':True,'widget':MoneyInput}}
    def get_list_display(self,request):
        fields=list(super().get_list_display(request))
        if hasattr(self.model,'is_default') and 'is_default' not in fields:fields.append('is_default')
        if hasattr(self.model,'is_hidden') and 'is_hidden' not in fields:fields.append('is_hidden')
        return fields
    def get_search_results(self,request,queryset,search_term):
        queryset,duplicates=super().get_search_results(request,queryset,search_term)
        if request.path.endswith('/autocomplete/') and hasattr(self.model,'is_hidden'):
            queryset=queryset.filter(is_hidden=False)
        return queryset,duplicates
    def get_form(self,request,obj=None,**kwargs):
        base=super().get_form(request,obj,**kwargs)
        from .reference_defaults import apply_reference_defaults
        class ReferenceDefaultForm(base):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                apply_reference_defaults(self,kwargs.get('initial'))
        return ReferenceDefaultForm
    def save_model(self,request,obj,form,change):
        old=type(obj).objects.filter(pk=obj.pk).values().first() if change else None
        super().save_model(request,obj,form,change)
        new=type(obj).objects.filter(pk=obj.pk).values().get()
        changes={k:{'old':str(old.get(k)) if old else None,'new':str(v)} for k,v in new.items() if not old or old.get(k)!=v}
        AuditEvent.objects.create(actor=request.user,object_type=obj._meta.label,object_id=str(obj.pk),action='updated' if change else 'created',changes=changes)
    def delete_model(self,request,obj):
        AuditEvent.objects.create(actor=request.user,object_type=obj._meta.label,object_id=str(obj.pk),action='deleted')
        super().delete_model(request,obj)
    def delete_queryset(self,request,queryset):
        for obj in queryset: self.delete_model(request,obj)

class LineInline(admin.TabularInline):
    from .card_forms import LineCardForm
    form=LineCardForm
    formfield_overrides={models.DecimalField:{'localize':True,'widget':MoneyInput}}
    model=ContractLine
    extra=1
    autocomplete_fields=['tourist']
class BookingInline(admin.TabularInline):
    model=Booking
    extra=0
    fields=['number','open_booking']
    readonly_fields=['open_booking']
    @admin.display(description='Бронь у туроператора')
    def open_booking(self,obj):
        if not obj.pk:return 'Сохраните договор и номер брони'
        return booking_button(obj.booking_link)

def booking_button(url):
    from urllib.parse import urlsplit
    try:
        if url and urlsplit(url).scheme in ('http','https'):
            return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">Перейти к брони ТО ↗</a>',url)
    except ValueError:
        pass
    return 'Укажите шаблон ссылки в карточке ТО'

def task_booking_links(task):
    operator=task.contract.operator if task.contract_id else task.operator
    if task.booking_number:
        return booking_button(operator.booking_link(task.booking_number)) if operator else 'Не выбран ТО'
    if task.contract_id:
        from django.utils.html import format_html_join
        return format_html_join(' · ','{}',((booking_button(b.booking_link),) for b in task.contract.bookings.all())) or 'Броней пока нет'
    return '—'


class PaymentInline(admin.TabularInline):
    from .card_forms import CardPaymentForm
    form=CardPaymentForm
    formfield_overrides={models.DecimalField:{'localize':True,'widget':MoneyInput}}
    model=Payment
    extra=0
    fields=['date','kind','method','amount','currency','rate','notes']
    verbose_name_plural='Финансы по договору'
    show_change_link=True

@admin.register(Contract)
class ContractAdmin(AuditedAdmin):
    list_per_page=50
    show_full_result_count=False
    list_select_related=['customer','operator']
    def get_queryset(self,request):
        from .financial_queries import with_financials
        return with_financials(super().get_queryset(request)).select_related('customer','operator').defer('source_data','legacy_customer_snapshot')
    change_list_template='admin/crm/contract/change_list.html'
    form=ContractForm
    def get_form(self,request,obj=None,**kwargs):
        attrs={}
        templates=TaskType.objects.filter(for_contract=True,is_hidden=False)
        if obj is not None:
            templates=templates.exclude(task__contract=obj)
        for template in templates:
            schedule=contract_task_schedule(obj or Contract(),template)
            attrs[f'task_due_{template.pk}']=forms.DateField(label=f'Срок: {template.name}',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','data-task-anchor':schedule['anchor'],'data-task-offset':schedule['offset'],'data-task-id':template.pk}))
        kwargs['form']=type('ContractWithTaskDates',(ContractForm,),attrs)
        return super().get_form(request,obj,**kwargs)
    readonly_fields=['financial_summary','tourvisor_id','tourvisor_time','imported_at','imported_stays','imported_flights','imported_services','imported_comments']
    def get_readonly_fields(self,request,obj=None):
        return list(self.readonly_fields)+(['number','date'] if obj and obj.tourvisor_id else [])
    @admin.display(description='Проживание из Турвизора')
    def imported_stays(self,obj):return source_table(obj,'hotel')
    @admin.display(description='Перелёты из Турвизора (ручные дополнения — поле «Рейсы туда и обратно»)')
    def imported_flights(self,obj):return source_table(obj,'transport')
    @admin.display(description='Услуги из Турвизора')
    def imported_services(self,obj):return ', '.join(str(s.get('name','')) for s in obj.source_data.get('service',[])) or '—'
    @admin.display(description='Комментарий из Турвизора')
    def imported_comments(self,obj):return obj.source_data.get('comments','') or '—'

    @admin.display(description='Итоги финансов')
    def financial_summary(self,obj):
        if not obj or not obj.pk:return 'Итоги появятся после сохранения договора'
        return format_html('Сумма: {} ₽ · Оплачено: {} ₽ · Долг: {} ₽ · Себестоимость: {} ₽ · Доход: {} ₽',money(obj.amount),money(obj.paid),money(obj.debt),money(obj.cost),money(obj.profit))
    inlines=[LineInline,BookingInline,PaymentInline]
    list_display=['id','number','date','customer','operator','start','end','display_amount','display_paid','display_cost','display_profit']
    list_filter=['operator','country','payment_method','date','start']
    search_fields=['number','customer__name','bookings__number','hotel']
    autocomplete_fields=['customer','operator']
    actions=['generate_tasks','duplicate']
    def changelist_view(self,request,extra_context=None):
        response=super().changelist_view(request,extra_context)
        if hasattr(response,'context_data') and response.context_data and response.context_data.get('cl'):
            qs=response.context_data['cl'].queryset
            totals=qs.aggregate(amount=Sum('_financial_amount'),paid=Sum('_customer_net'),cost=Sum('_financial_cost'))
            amount=totals['amount'] or 0;paid=totals['paid'] or 0;cost=totals['cost'] or 0
            response.context_data['contract_totals']={'count':qs.count(),**{key:money(value) for key,value in {'amount':amount,'paid':paid,'debt':amount-paid,'cost':cost,'profit':amount-cost}.items()}}
        return response
    @admin.display(description='Сумма, ₽')
    def display_amount(self,obj):return money(obj.amount)
    @admin.display(description='Оплачено, ₽')
    def display_paid(self,obj):return money(obj.paid)
    @admin.display(description='Себестоимость, ₽')
    def display_cost(self,obj):return money(obj.cost)
    @admin.display(description='Доход, ₽')
    def display_profit(self,obj):return money(obj.profit)
    @admin.action(description='Добавить задачи по активным шаблонам')
    def generate_tasks(self,request,queryset):
        if not request.user.has_perm('crm.add_task'): raise PermissionDenied
        for c in queryset: create_tasks(c)
        self.message_user(request,'Недостающие задачи добавлены. Существующие не изменены.')
    @admin.action(description='Копировать договор без оплат, броней и задач')
    def duplicate(self,request,queryset):
        if not request.user.has_perm('crm.add_contract'): raise PermissionDenied
        if queryset.count()!=1:
            self.message_user(request,'Выберите один договор',messages.ERROR);return
        c=copy_contract(queryset.get())
        AuditEvent.objects.create(actor=request.user,object_type='crm.Contract',object_id=str(c.pk),action='copied')
        self.message_user(request,format_html('Создан <a href="{}">договор №{}</a>',reverse('admin:crm_contract_change',args=[c.pk]),c.pk))
    def save_related(self,request,form,formsets,change):
        super().save_related(request,form,formsets,change)
        selected=form.cleaned_data.get('task_templates',[])
        if selected and not request.user.has_perm('crm.add_task'):
            raise PermissionDenied
        dates={t.pk:form.cleaned_data.get(f'task_due_{t.pk}') for t in selected}
        create_contract_tasks(form.instance,selected,dates)
        for fs in formsets:
            for obj in fs.new_objects + fs.changed_objects:
                instance=obj[0] if isinstance(obj,tuple) else obj
                AuditEvent.objects.create(actor=request.user,object_type=instance._meta.label,object_id=str(instance.pk),action='inline_saved')

@admin.register(Customer)
class CustomerAdmin(AuditedAdmin):
    list_editable=['is_default']
    from .forms import CustomerForm
    form=CustomerForm
    list_display=['name','kind','inn','main_phone','main_email','phones','emails','is_default']
    search_fields=['name','company_name','inn','representative','main_phone','main_email','phones','emails']
    readonly_fields=['contracts_link']
    @admin.display(description='Договоры заказчика')
    def contracts_link(self,obj):
        if obj.pk:return format_html('<a href="{}?customer__id__exact={}">Открыть договоры</a>',reverse('admin:crm_contract_changelist'),obj.pk)
        return 'Сохраните заказчика'
@admin.register(Tourist)
class TouristAdmin(AuditedAdmin):
    from .forms import TouristForm
    form=TouristForm
    list_editable=['is_default']
    list_display=['name','birthday','customer','is_default']
    search_fields=['name']
@admin.register(Operator)
class OperatorAdmin(AuditedAdmin):
    list_editable=['sort_order','is_default']
    search_fields=['name']
    list_display=['name','booking_url_template','sort_order','is_default']

@admin.register(ContractType,PaymentMethod,Meal,Transfer,Insurance,FuelSurcharge)
class ReferenceAdmin(AuditedAdmin):
    list_editable=['sort_order','is_default']
    search_fields=['name']
    list_display=['name','sort_order','is_default']
@admin.register(Payment)
class PaymentAdmin(AuditedAdmin):
    change_list_template='admin/crm/payment/change_list.html'
    form=PaymentForm
    fields=['customer','contract','date','kind','method','amount','currency','rate','notes']
    list_display=['date','customer_name','contract','kind','incoming_amount','outgoing_amount','method','display_rate']
    list_filter=['kind','method','date','contract__customer']
    search_fields=['contract__number','contract__customer__name','legacy_payer__name']
    list_select_related=['contract__customer','legacy_payer','method']
    @admin.display(description='Поступление, ₽')
    def incoming_amount(self,obj):return money(obj.amount if obj.kind in ('customer','operator_refund') else 0)
    @admin.display(description='Расход, ₽')
    def outgoing_amount(self,obj):return money(obj.amount if obj.kind in ('operator','customer_refund') else 0)
    @admin.display(description='Курс')
    def display_rate(self,obj):return money(obj.rate)
    def changelist_view(self,request,extra_context=None):
        response=super().changelist_view(request,extra_context)
        if hasattr(response,'context_data') and response.context_data and response.context_data.get('cl'):
            qs=response.context_data['cl'].queryset
            response.context_data['financial_totals']={'count':qs.count(),'incoming':money(qs.filter(kind__in=['customer','operator_refund']).aggregate(s=Sum('amount'))['s'] or 0),'outgoing':money(qs.filter(kind__in=['operator','customer_refund']).aggregate(s=Sum('amount'))['s'] or 0)}
        return response
    @admin.display(description='Заказчик',ordering='contract__customer__name')
    def customer_name(self,obj):return obj.payer
    def get_urls(self):
        return [path('contracts-for-customer/',self.admin_site.admin_view(self.contracts_for_customer),name='crm_payment_contracts_for_customer')]+super().get_urls()
    def contracts_for_customer(self,request):
        if not (self.has_add_permission(request) or self.has_change_permission(request)) or not request.user.has_perm('crm.view_contract'):
            raise PermissionDenied
        contracts=Contract.objects.select_related('customer').order_by('-date','-pk')
        customer=request.GET.get('customer')
        if customer:
            if not customer.isdigit():return JsonResponse({'contracts':[]})
            contracts=contracts.filter(customer_id=customer)
        return JsonResponse({'contracts':[{'id':c.pk,'label':f'{c} · {c.customer}'} for c in contracts]})
class TaskForm(forms.ModelForm):
    repeat = forms.ChoiceField(label='Повтор',choices=[('','Без повтора'),('day','Каждый день'),('week','Каждую неделю'),('month','Каждый месяц'),('year','Каждый год')],required=False)
    occurrences = forms.IntegerField(label='Всего задач (включая первую)',min_value=1,max_value=366,initial=1,help_text='Все задачи создаются сразу; максимум 366 за один раз.')
    class Meta:
        model=Task
        fields='__all__'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk:
            self.fields.pop('repeat');self.fields.pop('occurrences')

@admin.register(Task)
class TaskAdmin(AuditedAdmin):
    form=TaskForm
    def get_fields(self,request,obj=None):
        fields=super().get_fields(request,obj)
        if obj is not None:
            fields=[field for field in fields if field not in ('repeat','occurrences')]
        return fields
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        if not change and form.cleaned_data.get('repeat'):
            from .services import repeat_tasks
            copies=repeat_tasks(obj,form.cleaned_data['repeat'],form.cleaned_data['occurrences'])
            for copy in copies:
                AuditEvent.objects.create(actor=request.user,object_type='crm.Task',object_id=str(copy.pk),action='created_repeat')
    list_display=['title','due','done','employee','customer','contract','tour_operator','booking_numbers','booking_links']
    readonly_fields=['tour_operator','booking_numbers','booking_links']
    list_filter=['done','due','employee']
    list_editable=['done']
    exclude=['template']
    autocomplete_fields=['contract','customer']
    search_fields=['title','description','booking_number','contract__bookings__number','contract__operator__name']
    @admin.display(description='Туроператор')
    def tour_operator(self,obj):return obj.contract.operator if obj.contract_id else (obj.operator or '—')
    @admin.display(description='Брони ТО')
    def booking_numbers(self,obj):
        return obj.booking_number or (', '.join(obj.contract.bookings.values_list('number',flat=True)) if obj.contract_id else '—')
    @admin.display(description='Перейти к брони')
    def booking_links(self,obj):return task_booking_links(obj)
@admin.register(TaskTemplate)
class TemplateAdmin(AuditedAdmin):
    list_display=['name','anchor','offset','order','copy_flights','active']
    list_editable=['order']
@admin.register(AuditEvent)
class AuditAdmin(admin.ModelAdmin):
    list_display=['at','actor','object_type','object_id','action']
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

admin.site.site_header='АБОРИГЕН-ТУР · CRM'
admin.site.site_title='АБОРИГЕН-ТУР'
admin.site.index_title='Управление агентством'


@admin.register(DepartureCity,Country)
class LocationAdmin(AuditedAdmin):
    list_editable=['sort_order','is_default']
    list_display=['name','code','sort_order','is_default']
    search_fields=['name','code']
    readonly_fields=['details']


SOURCE_LABELS={'name':'Название','country':'Страна','region':'Регион','startdate':'Дата начала','nights':'Ночей','room':'Номер','meal':'Питание','placement':'Размещение','direction':'Направление','number':'Рейс','datefrom':'Дата вылета','dateto':'Дата прилёта','timefrom':'Время вылета','timeto':'Время прилёта','aircompany':'Авиакомпания','plane':'Самолёт','terminalfrom':'Откуда','terminalto':'Куда','terminalcodefrom':'Код аэропорта вылета','terminalcodeto':'Код аэропорта прилёта'}
def source_table(obj,key):
    entries=obj.source_data.get(key,[]) if obj else []
    if not entries:return '—'
    return format_html_join('', '<div style="margin-bottom:14px">{}</div>',((format_html_join(' · ','<span><b>{}</b>: {}</span>',((SOURCE_LABELS.get(k,k),v) for k,v in entry.items())),) for entry in entries))

@admin.register(Currency)
class CurrencyAdmin(AuditedAdmin):
    list_editable=['sort_order','is_default']
    list_display=['code','name','sort_order','is_default']
    search_fields=['code','name']


from .models import PaymentOperation
@admin.register(PaymentOperation)
class PaymentOperationAdmin(AuditedAdmin):
    list_display=['code','name','is_default']
    list_editable=['name','is_default']
    readonly_fields=['code']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False

from .models import TaskType
@admin.register(TaskType)
class TaskTypeAdmin(AuditedAdmin):
    list_display=['name','description','sort_order','for_contract','is_default']
    list_editable=['sort_order','for_contract','is_default']
    search_fields=['name','description']


from .models import LibraryEntry,LibraryAttachment,LegacyImportRun
@admin.register(LibraryEntry)
class LibraryEntryAdmin(AuditedAdmin):
    list_display=['title','parent','sort_order']
    search_fields=['title','search_text']
    fields=['title','parent','body','sort_order']

@admin.register(LegacyImportRun)
class LegacyImportRunAdmin(admin.ModelAdmin):
    list_display=['created_at','section','source_key','actor']
    readonly_fields=['source_key','section','content_sha256','source_snapshot','created_at','actor','summary','issues']
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

from .models import LegacyRecord
@admin.register(LegacyRecord)
class LegacyRecordAdmin(admin.ModelAdmin):
    def has_view_permission(self,request,obj=None):return request.user.is_active and request.user.is_superuser
    list_display=['table','source_id','target_model','target_id','status','import_run']
    list_filter=['table','status']
    search_fields=['=source_id','=target_id']
    readonly_fields=['source_key','table','source_id','import_run','payload','target_model','target_id','status']
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False


# Archive a staff choice independently of the employee's permission to sign in.
from django.contrib.auth import get_user_model
from .models import EmployeeVisibility
class EmployeeVisibilityInline(admin.StackedInline):
    model=EmployeeVisibility
    extra=1
    max_num=1
admin.site._registry[get_user_model()].inlines=tuple(admin.site._registry[get_user_model()].inlines)+(EmployeeVisibilityInline,)
