from django.db.models import Q
from django import forms
from .forms import ContractForm,CustomerForm,TouristForm
from .models import Customer,Tourist,Payment,Booking,ContractLine,Task,TaskType,TaskTemplate,Currency
from .services import task_due,contract_task_schedule
from .widgets import MoneyInput
from .reference_defaults import apply_reference_defaults

class CardContractForm(ContractForm):
    version=forms.CharField(widget=forms.HiddenInput,required=False)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['version'].initial=str(self.instance.updated_at) if self.instance.pk else ''
        if self.instance.tourvisor_id:
            self.fields['number'].disabled=True;self.fields['date'].disabled=True
        for name,field in self.fields.items():
            if isinstance(field,forms.DateField):field.widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'})
            elif isinstance(field.widget,forms.Textarea):field.widget.attrs['rows']=3
        templates=self.fields['task_templates'].queryset
        for t in templates:
            schedule=contract_task_schedule(self.instance,t)
            self.fields[f'task_due_{t.pk}']=forms.DateField(label=f'Срок: {t.name}',required=False,initial=schedule['due'],widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','data-task-anchor':schedule['anchor'],'data-task-offset':schedule['offset'],'data-task-id':t.pk}))

class CustomerCardForm(CustomerForm):
    class Meta:
        model=Customer
        fields=['kind','company_name','inn','kpp','ogrn','legal_address','bank_name','bik','account','correspondent_account','representative','representative_basis','passport_type','name','surname','given_name','patronymic','birthday','main_phone','main_email','phones','emails','address','passport_number','passport_issued','passport_issued_by','passport_code','passport']
        widgets={'birthday':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'passport_issued':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'})}

class TouristCardForm(TouristForm):
    class Meta:
        model=Tourist
        fields=['name','surname','given_name','gender','birthday','passport_type','passport_number','issued','expires','issued_by','birthcountry','nationality','is_customer']
        widgets={k:forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}) for k in ('birthday','issued','expires')}

class CardPaymentForm(forms.ModelForm):
    class Meta:
        model=Payment
        fields=['date','kind','method','amount','currency','rate','notes']
        widgets={'date':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'amount':MoneyInput(),'rate':MoneyInput(),'notes':forms.Textarea(attrs={'rows':2})}
        localized_fields=['amount','rate']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from .models import payment_operation_choices
        self.fields['kind'].choices=[('','—')]+payment_operation_choices()
        self.fields['currency']=forms.ChoiceField(label='Валюта оплаты ТО (справочно)',required=False,initial='RUB',choices=[('','—')]+[(c.code,str(c)) for c in Currency.objects.filter(Q(is_hidden=False)|Q(code=getattr(self.instance,'source_currency',''))|Q(code=getattr(self.instance,'currency','')))])
        apply_reference_defaults(self,kwargs.get('initial'))

class BookingCardForm(forms.ModelForm):
    class Meta:
        model=Booking
        fields=['number']

class LineCardForm(forms.ModelForm):
    class Media:
        js=['crm/remote_choices.js']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        apply_reference_defaults(self,kwargs.get('initial'))
        field=self.fields['tourist']
        if not field.widget.__class__.__module__.startswith('django.contrib.admin'):
            selected=self.data.get(self.add_prefix('tourist')) if self.is_bound else self.instance.tourist_id or self.initial.get('tourist') or field.initial
            choices=Tourist.objects.filter(pk=selected).only('pk','name') if selected and str(selected).isdigit() else Tourist.objects.none()
            field.widget.choices=[('','---------')]+[(t.pk,t.name) for t in choices]
            field.widget.attrs['data-remote-choices']='/tourists/search/'
    class Meta:
        model=ContractLine
        fields=['tourist','description','amount']
        widgets={'amount':MoneyInput()}
        localized_fields=['amount']

class TaskCardForm(forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['task_type'].label='Задача'
        if self.instance.pk and not self.instance.task_type_id:
            self.fields['task_type'].empty_label=self.instance.title+' (текущее)'
            self.fields['task_type'].required=False
        elif not self.is_bound or not self.data.get(self.add_prefix('title')):self.fields['task_type'].required=True
        apply_reference_defaults(self,kwargs.get('initial'))
    def clean(self):
        data=super().clean()
        kind=data.get('task_type')
        if kind:
            self.instance.title=kind.name
            if not data.get('description'):data['description']=kind.description
        elif self.is_bound and self.data.get(self.add_prefix('title')):
            self.instance.title=self.data[self.add_prefix('title')]
        return data
    class Meta:
        model=Task
        fields=['task_type','description','due','employee','done']
        widgets={'due':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'description':forms.Textarea(attrs={'rows':2})}
