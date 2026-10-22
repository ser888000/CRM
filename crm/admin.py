from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import LogEntry
from django.urls import reverse
from django.utils.html import format_html
from .models import Customer, Operator, Tourist, Contract, Booking, ContractLine, Payment, Task, TaskTemplate, AuditEvent
from .services import create_tasks, copy_contract

class AuditedAdmin(admin.ModelAdmin):
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
    model=ContractLine
    extra=1
    autocomplete_fields=['tourist']
class BookingInline(admin.TabularInline):
    model=Booking
    extra=0

class ContractForm(forms.ModelForm):
    task_templates = forms.ModelMultipleChoiceField(label='Создать задачи по шаблонам (только при создании)',queryset=TaskTemplate.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    class Meta:
        model=Contract
        fields='__all__'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if not self.instance.pk:self.fields['task_templates'].initial=TaskTemplate.objects.filter(active=True)
        else:self.fields.pop('task_templates')

@admin.register(Contract)
class ContractAdmin(AuditedAdmin):
    form=ContractForm
    def get_fields(self,request,obj=None):
        fields=super().get_fields(request,obj)
        if obj is not None:
            fields=[field for field in fields if field != 'task_templates']
        return fields
    inlines=[LineInline,BookingInline]
    list_display=['id','number','date','customer','operator','start','end','amount','paid','cost','profit']
    list_filter=['operator','country','payment_method','date','start']
    search_fields=['number','customer__name','bookings__number','hotel']
    autocomplete_fields=['customer','operator']
    actions=['generate_tasks','duplicate']
    @admin.action(description='Добавить задачи по активным шаблонам')
    def generate_tasks(self,request,queryset):
        if not request.user.has_perm('crm.add_task'): raise PermissionError
        for c in queryset: create_tasks(c)
        self.message_user(request,'Недостающие задачи добавлены. Существующие не изменены.')
    @admin.action(description='Копировать договор без оплат, броней и задач')
    def duplicate(self,request,queryset):
        if not request.user.has_perm('crm.add_contract'): raise PermissionError
        if queryset.count()!=1:
            self.message_user(request,'Выберите один договор',messages.ERROR);return
        c=copy_contract(queryset.get())
        AuditEvent.objects.create(actor=request.user,object_type='crm.Contract',object_id=str(c.pk),action='copied')
        self.message_user(request,format_html('Создан <a href="{}">договор №{}</a>',reverse('admin:crm_contract_change',args=[c.pk]),c.pk))
    def save_related(self,request,form,formsets,change):
        super().save_related(request,form,formsets,change)
        if not change:
            from datetime import timedelta
            for template in form.cleaned_data.get('task_templates',[]):
                anchor={'created':form.instance.date,'start':form.instance.start,'end':form.instance.end}[template.anchor]
                if anchor:
                    Task.objects.get_or_create(origin_key=f'contract:{form.instance.pk}:template:{template.pk}',defaults={'template':template,'contract':form.instance,'customer':form.instance.customer,'title':template.name,'due':anchor+timedelta(days=template.offset)})
                else:self.message_user(request,f'Для задачи «{template.name}» не задана дата тура; создайте её вручную.',messages.WARNING)
        for fs in formsets:
            for obj in fs.new_objects + fs.changed_objects:
                instance=obj[0] if isinstance(obj,tuple) else obj
                AuditEvent.objects.create(actor=request.user,object_type=instance._meta.label,object_id=str(instance.pk),action='inline_saved')

@admin.register(Customer)
class CustomerAdmin(AuditedAdmin):
    list_display=['name','phones','emails']
    search_fields=['name','phones','emails']
    readonly_fields=['contracts_link']
    @admin.display(description='Договоры заказчика')
    def contracts_link(self,obj):
        if obj.pk:return format_html('<a href="{}?customer__id__exact={}">Открыть договоры</a>',reverse('admin:crm_contract_changelist'),obj.pk)
        return 'Сохраните заказчика'
@admin.register(Tourist)
class TouristAdmin(AuditedAdmin):
    list_display=['name','birthday','customer']
    search_fields=['name']
@admin.register(Operator)
class OperatorAdmin(AuditedAdmin):
    search_fields=['name']
@admin.register(Payment)
class PaymentAdmin(AuditedAdmin):
    list_display=['date','contract','kind','amount','method']
    list_filter=['kind','method','date']
    autocomplete_fields=['contract']
    search_fields=['contract__number','contract__customer__name']
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
    list_display=['title','due','done','employee','customer','contract']
    list_filter=['done','due','employee']
    list_editable=['done']
    exclude=['template']
    autocomplete_fields=['contract','customer']
    search_fields=['title','description']
@admin.register(TaskTemplate)
class TemplateAdmin(AuditedAdmin):
    list_display=['name','anchor','offset','active']
@admin.register(AuditEvent)
class AuditAdmin(admin.ModelAdmin):
    list_display=['at','actor','object_type','object_id','action']
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

admin.site.site_header='АБОРИГЕН-ТУР · CRM'
admin.site.site_title='АБОРИГЕН-ТУР'
admin.site.index_title='Управление агентством'
