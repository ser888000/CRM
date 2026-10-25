from django.db.models import Q
from django import forms
from .models import Contract,TaskType,Payment,Customer,Tourist,DepartureCity,Country,Currency,Meal,Transfer,Insurance,FuelSurcharge
from .services import contract_task_schedule
from .widgets import LocationInput,MoneyInput
from .reference_defaults import apply_reference_defaults

class ContractForm(forms.ModelForm):
    task_templates=forms.ModelMultipleChoiceField(label='Создать задачи (снимите ненужные)',queryset=TaskType.objects.filter(for_contract=True,is_hidden=False),required=False,widget=forms.CheckboxSelectMultiple)
    class Meta:
        model=Contract
        fields='__all__'
        widgets={'departure':LocationInput(DepartureCity),'country':LocationInput(Country),'meal':LocationInput(Meal),'transfer':LocationInput(Transfer),'insurance':LocationInput(Insurance),'fuel_surcharge':LocationInput(FuelSurcharge)}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['source_currency']=forms.ChoiceField(label='Валюта предложения',choices=[(c.code,str(c)) for c in Currency.objects.filter(Q(is_hidden=False)|Q(code=getattr(self.instance,'source_currency',''))|Q(code=getattr(self.instance,'currency','')))],initial='RUB')
        if not self.instance.pk:self.initial.setdefault('source_currency','RUB')
        if self.instance.pk:
            self.fields['task_templates'].queryset=TaskType.objects.filter(for_contract=True,is_hidden=False).exclude(task__contract=self.instance)
            self.fields['task_templates'].initial=[]
        else:
            self.fields['task_templates'].initial=TaskType.objects.filter(for_contract=True,is_hidden=False)
        apply_reference_defaults(self,kwargs.get('initial'))
        for template in self.fields['task_templates'].queryset:
            field=self.fields.get(f'task_due_{template.pk}')
            if field:
                field.initial=contract_task_schedule(self.instance,template)['due']
    def clean_departure(self):
        value=self.cleaned_data['departure']
        reference=DepartureCity.match(value) if value else None
        return reference.name if reference else value
    def clean_country(self):
        value=self.cleaned_data['country']
        reference=Country.match(value) if value else None
        return reference.name if reference else value
    def clean(self):
        data=super().clean()
        for template in data.get('task_templates',[]):
            if not data.get(f'task_due_{template.pk}'):
                self.add_error(f'task_due_{template.pk}','Укажите срок выбранной задачи.')
        return data
    class Media:
        js=['crm/task_dates.js']

class PaymentForm(forms.ModelForm):
    customer=forms.ModelChoiceField(label='Заказчик',queryset=Customer.objects.all(),required=False,help_text='Выберите заказчика для отбора договоров или сразу укажите договор.')
    class Meta:
        model=Payment
        fields='__all__'
        widgets={'rate':MoneyInput(),'amount':MoneyInput()}
        localized_fields=['amount','rate']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from .models import payment_operation_choices
        self.fields['kind'].choices=[('','—')]+payment_operation_choices()
        self.fields['currency']=forms.ChoiceField(label='Справочно: валюта оплаты ТО',required=False,initial='RUB',choices=[('','---------')]+[(c.code,str(c)) for c in Currency.objects.filter(Q(is_hidden=False)|Q(code=getattr(self.instance,'source_currency',''))|Q(code=getattr(self.instance,'currency','')))])
        customer=None
        if self.is_bound:
            customer=self.data.get(self.add_prefix('customer'))
        elif self.instance.pk:
            customer=self.instance.contract.customer_id
        else:
            customer=self.initial.get('customer')
        if customer:
            try:
                customer=int(customer)
                self.fields['contract'].queryset=Contract.objects.filter(customer_id=customer).select_related('customer')
                self.fields['customer'].initial=customer
            except (ValueError,TypeError):
                self.fields['contract'].queryset=Contract.objects.none()
        else:
            self.fields['contract'].queryset=Contract.objects.select_related('customer').all()
        self.fields['contract'].label_from_instance=lambda c:f'{c} · {c.customer}'
        apply_reference_defaults(self,kwargs.get('initial'))
    class Media:
        js=['crm/payment_customer_v2.js']


class CustomerForm(forms.ModelForm):
    class Meta:
        model=Customer
        fields='__all__'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['kind'].required=False
        self.fields['passport_type'].required=False
        self.fields['name'].required=False
        self.fields['name'].widget.attrs['readonly']=True
        self.order_fields(['kind','company_name','inn','kpp','ogrn','legal_address','bank_name','bik','account','correspondent_account','representative','representative_basis','surname','given_name','patronymic','name','birthday','main_phone','phones','main_email','emails','passport_type','passport_number','passport_issued','passport_issued_by','passport_code','address','passport'])
        for field in self.fields.values():
            if isinstance(field.widget,forms.Textarea):field.widget.attrs['rows']=3
    def clean(self):
        data=super().clean()
        data['passport_type']=data.get('passport_type') or (self.instance.passport_type if self.instance.pk else '1')
        data['kind']=data.get('kind') or (self.instance.kind if self.instance.pk else 'person')
        full=' '.join(data.get(k,'').strip() for k in ('surname','given_name','patronymic') if data.get(k,'').strip())
        data['name']=data.get('company_name','').strip() if data.get('kind')=='company' else full or data.get('name','').strip()
        if not data['name']:self.add_error('company_name' if data.get('kind')=='company' else 'surname','Укажите наименование организации.' if data.get('kind')=='company' else 'Укажите фамилию и имя заказчика.')
        import re
        for key,lengths in [('inn',(10,12)),('kpp',(9,)),('ogrn',(13,15)),('bik',(9,)),('account',(20,)),('correspondent_account',(20,))]:
            value=data.get(key,'').strip()
            if data['kind']=='company' and value and (not re.fullmatch(r'[0-9]+',value) or len(value) not in lengths):self.add_error(key,'Проверьте количество цифр: '+', '.join(map(str,lengths))+'.')
        return data
    class Media:
        js=['crm/customer_name_v2.js']


class TouristForm(forms.ModelForm):
    class Meta:
        model=Tourist
        fields='__all__'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['name'].required=False
        self.fields['name'].widget.attrs.update({'readonly':True,'data-person-name':'tourist'})
        apply_reference_defaults(self,kwargs.get('initial'))
        self.order_fields(['surname','given_name','name'])
    def clean(self):
        data=super().clean()
        full=' '.join(data.get(key,'').strip() for key in ('surname','given_name') if data.get(key,'').strip())
        data['name']=full or data.get('name','').strip()
        if not data['name']:self.add_error('surname','Укажите фамилию и имя туриста.')
        return data
    class Media:
        js=['crm/customer_name_v2.js']
