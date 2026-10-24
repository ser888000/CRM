from django import forms
from .models import Contract,TaskTemplate,Payment,Customer,DepartureCity,Country,Currency,Meal,Transfer,Insurance,FuelSurcharge
from .services import task_due
from .widgets import LocationInput,MoneyInput

class ContractForm(forms.ModelForm):
    task_templates=forms.ModelMultipleChoiceField(label='Создать задачи (снимите ненужные)',queryset=TaskTemplate.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    class Meta:
        model=Contract
        fields='__all__'
        widgets={'departure':LocationInput(DepartureCity),'country':LocationInput(Country),'meal':LocationInput(Meal),'transfer':LocationInput(Transfer),'insurance':LocationInput(Insurance),'fuel_surcharge':LocationInput(FuelSurcharge)}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['source_currency']=forms.ChoiceField(label='Валюта предложения',choices=[(c.code,str(c)) for c in Currency.objects.all()],initial='RUB')
        if not self.instance.pk:self.initial.setdefault('source_currency','RUB')
        if self.instance.pk:
            self.fields['task_templates'].queryset=TaskTemplate.objects.exclude(task__contract=self.instance)
            self.fields['task_templates'].initial=[]
        else:
            self.fields['task_templates'].initial=TaskTemplate.objects.filter(active=True)
        for template in TaskTemplate.objects.all():
            field=self.fields.get(f'task_due_{template.pk}')
            if field:
                field.initial=task_due(self.instance,template)
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
        self.fields['currency']=forms.ChoiceField(label='Справочно: валюта оплаты ТО',required=False,initial='RUB',choices=[('','---------')]+[(c.code,str(c)) for c in Currency.objects.all()])
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
    class Media:
        js=['crm/payment_customer.js']


class CustomerForm(forms.ModelForm):
    class Meta:
        model=Customer
        fields='__all__'
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['name'].required=False
        self.fields['name'].widget.attrs['readonly']=True
        self.order_fields(['surname','given_name','patronymic','name','birthday','main_phone','phones','main_email','emails'])
        for field in self.fields.values():
            if isinstance(field.widget,forms.Textarea):field.widget.attrs['rows']=3
    def clean(self):
        data=super().clean()
        full=' '.join(data.get(k,'').strip() for k in ('surname','given_name','patronymic') if data.get(k,'').strip())
        data['name']=full or data.get('name','').strip()
        if not data['name']:self.add_error('surname','Укажите фамилию и имя заказчика.')
        return data
    class Media:
        js=['crm/customer_name.js']
