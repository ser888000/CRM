from django import forms
from .models import Currency,Country,DepartureCity,Meal,Transfer,Insurance,FuelSurcharge,PaymentOperation,Payment

TEXT_REFERENCES={'kind':PaymentOperation,'source_currency':Currency,'currency':Currency,'country':Country,'departure':DepartureCity,'meal':Meal,'transfer':Transfer,'insurance':Insurance,'fuel_surcharge':FuelSurcharge}

def apply_reference_defaults(form,explicit=None):
    if form.is_bound or (getattr(form,'instance',None) and form.instance.pk):return
    explicit=explicit or {}
    for name,field in form.fields.items():
        if name in explicit or isinstance(field,forms.ModelMultipleChoiceField):continue
        if name=='kind' and not isinstance(getattr(form,'instance',None),Payment):continue
        if name in TEXT_REFERENCES:
            model=TEXT_REFERENCES[name];record=model.objects.filter(is_default=True).first()
            if record:form.initial[name]=record.code if model in (Currency,PaymentOperation) else record.name
        elif isinstance(field,forms.ModelChoiceField) and hasattr(field.queryset.model,'is_default'):
            record=field.queryset.filter(is_default=True).first()
            if record:form.initial[name]=record.pk
