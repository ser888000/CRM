from django import template
from django import forms
from crm.reference_defaults import TEXT_REFERENCES
from crm.models import Payment
from crm.reference_dialog import NAMES
register=template.Library()

@register.simple_tag(takes_context=True)
def reference_controls(context,field):
    request=context.get('request')
    if context.get('reference_popup') or not request or field.is_hidden:return None
    if field.name=='kind' and not isinstance(getattr(field.form,'instance',None),Payment):return None
    model=None;mode='id'
    if isinstance(field.field,forms.ModelChoiceField):model=field.field.queryset.model
    elif hasattr(field.field.widget,'reference_model'):model=field.field.widget.reference_model;mode='text'
    elif field.name in TEXT_REFERENCES:model=TEXT_REFERENCES[field.name];mode='code' if field.name in ('source_currency','currency','kind') else 'text'
    if not model or model._meta.model_name not in NAMES:return None
    base='/references/'+model._meta.model_name+'/'
    return {'base':base,'add':request.user.has_perm('crm.add_'+model._meta.model_name) and model._meta.model_name!='paymentoperation','change':request.user.has_perm('crm.change_'+model._meta.model_name),'mode':mode}
