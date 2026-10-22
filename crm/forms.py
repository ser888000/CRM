from django import forms
from .models import Contract,TaskTemplate,Payment,Customer,DepartureCity,Country
from .services import task_due
from .widgets import LocationInput

class ContractForm(forms.ModelForm):
    task_templates=forms.ModelMultipleChoiceField(label='Создать задачи (снимите ненужные)',queryset=TaskTemplate.objects.all(),required=False,widget=forms.CheckboxSelectMultiple)
    class Meta:
        model=Contract
        fields='__all__'
        widgets={'departure':LocationInput(DepartureCity),'country':LocationInput(Country)}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
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
        widgets={'rate':forms.NumberInput(attrs={'step':'0.01'})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
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
