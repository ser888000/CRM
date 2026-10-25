from django import forms
from .models import Currency,Country,DepartureCity,Meal,Transfer,Insurance,FuelSurcharge,PaymentOperation,Payment

TEXT_REFERENCES={'kind':PaymentOperation,'source_currency':Currency,'currency':Currency,'country':Country,'departure':DepartureCity,'meal':Meal,'transfer':Transfer,'insurance':Insurance,'fuel_surcharge':FuelSurcharge}

def apply_reference_defaults(form,explicit=None):
    # Keep the saved historical choice, but do not offer archived references for new selection.
    from django.db.models import Q
    for name,field in form.fields.items():
        if not isinstance(field,forms.ModelChoiceField):continue
        model=field.queryset.model
        current=getattr(getattr(form,'instance',None),name+'_id',None)
        if name=='customer' and isinstance(getattr(form,'instance',None),Payment) and form.instance.pk:
            current=form.instance.contract.customer_id
        if hasattr(model,'is_hidden'):
            field.queryset=field.queryset.filter(Q(is_hidden=False)|Q(pk=current))
        elif model._meta.label_lower=='auth.user':
            field.queryset=field.queryset.filter((Q(is_active=True)&~Q(directory_visibility__is_hidden=True))|Q(pk=current))
    if isinstance(getattr(form,'instance',None),Payment) and 'kind' in form.fields:
        hidden=set(PaymentOperation.objects.filter(is_hidden=True).values_list('code',flat=True))
        current=form.instance.kind if form.instance.pk else None
        form.fields['kind'].choices=[(code,label) for code,label in form.fields['kind'].choices if code not in hidden or code==current]
    if form.is_bound or (getattr(form,'instance',None) and form.instance.pk):return
    explicit=explicit or {}
    for name,field in form.fields.items():
        if name in explicit or isinstance(field,forms.ModelMultipleChoiceField):continue
        if name=='kind' and not isinstance(getattr(form,'instance',None),Payment):continue
        if name in TEXT_REFERENCES:
            model=TEXT_REFERENCES[name];record=model.objects.filter(is_default=True,is_hidden=False).first()
            if record:form.initial[name]=record.code if model in (Currency,PaymentOperation) else record.name
        elif isinstance(field,forms.ModelChoiceField) and hasattr(field.queryset.model,'is_default'):
            record=field.queryset.filter(is_default=True,is_hidden=False).first()
            if record:form.initial[name]=record.pk
