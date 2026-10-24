from django import forms
from .forms import ContractForm,CustomerForm
from .models import Customer,Tourist,Payment,Booking,ContractLine,Task,TaskTemplate,Currency
from .services import task_due
from .widgets import MoneyInput

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
            self.fields[f'task_due_{t.pk}']=forms.DateField(label=f'Срок: {t.name}',required=False,initial=task_due(self.instance,t),widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','data-task-anchor':t.anchor,'data-task-offset':t.offset,'data-task-id':t.pk}))

class CustomerCardForm(CustomerForm):
    class Meta:
        model=Customer
        fields=['name','surname','given_name','patronymic','birthday','main_phone','main_email','phones','emails','address','passport_number','passport_issued','passport_issued_by','passport_code','passport']
        widgets={'birthday':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'passport_issued':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'})}

class TouristCardForm(forms.ModelForm):
    class Meta:
        model=Tourist
        fields=['name','surname','given_name','gender','birthday','passport_type','passport_number','issued','expires','issued_by','birthcountry','nationality','is_customer']
        widgets={k:forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}) for k in ('birthday','issued','expires')}

class CardPaymentForm(forms.ModelForm):
    class Meta:
        model=Payment
        fields=['date','kind','amount','method','currency','rate','notes']
        widgets={'date':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'amount':MoneyInput(),'rate':MoneyInput(),'notes':forms.Textarea(attrs={'rows':2})}
        localized_fields=['amount','rate']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['currency']=forms.ChoiceField(label='Валюта оплаты ТО (справочно)',required=False,initial='RUB',choices=[('','—')]+[(c.code,str(c)) for c in Currency.objects.all()])

class BookingCardForm(forms.ModelForm):
    class Meta:
        model=Booking
        fields=['number']

class LineCardForm(forms.ModelForm):
    class Meta:
        model=ContractLine
        fields=['tourist','description','amount']
        widgets={'amount':MoneyInput()}
        localized_fields=['amount']

class TaskCardForm(forms.ModelForm):
    class Meta:
        model=Task
        fields=['title','description','due','employee','done']
        widgets={'due':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}),'description':forms.Textarea(attrs={'rows':2})}
