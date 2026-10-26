"""Permission checked reference editing in an embedded dialog."""
from django import forms
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404,render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.debug import sensitive_post_parameters
from django.db import transaction
from .card_forms import CustomerCardForm,TouristCardForm
from .models import AuditEvent
from django.forms.models import model_to_dict

NAMES={'customer','tourist','operator','contracttype','paymentmethod','meal','transfer','insurance','fuelsurcharge','country','departurecity','currency','tasktype','paymentoperation','tasktemplate'}

@login_required
@never_cache
@xframe_options_sameorigin
@sensitive_post_parameters()
@transaction.atomic
def edit(request,model_name,pk=None):
    if model_name not in NAMES:raise Http404
    model=apps.get_model('crm',model_name)
    if not request.user.has_perm('crm.'+('change_' if pk else 'add_')+model_name):raise PermissionDenied
    if model_name=='paymentoperation' and not pk:raise PermissionDenied
    instance=get_object_or_404(model,pk=pk) if pk else model()
    before=model_to_dict(instance) if pk else {}
    if model_name=='customer':formclass=CustomerCardForm
    elif model_name=='tourist':formclass=TouristCardForm
    else:
        fields=[f.name for f in model._meta.fields if f.editable and not f.primary_key and f.name!='details' and not (model_name=='paymentoperation' and f.name=='code')]
        formclass=forms.modelform_factory(model,fields=fields)
    form=formclass(request.POST if request.method=='POST' else None,instance=instance,prefix='reference')
    from .reference_defaults import apply_reference_defaults
    apply_reference_defaults(form)
    result=None
    if request.method=='POST' and form.is_valid():
        saved=form.save()
        AuditEvent.objects.create(actor=request.user,object_type=saved._meta.label,object_id=str(saved.pk),action='updated' if pk else 'created',changes={k:{'old':str(before.get(k)),'new':str(v)} for k,v in model_to_dict(saved).items() if before.get(k)!=v})
        result={'type':'crm-reference-saved','id':str(saved.pk),'label':str(saved),'text':getattr(saved,'name',str(saved)),'code':getattr(saved,'code','')}
    return render(request,'crm/reference_dialog.html',{'form':form,'result':result,'title':('Изменить: ' if pk else 'Добавить: ')+str(model._meta.verbose_name),'reference_action':model_name,'reference_popup':True})

@login_required
@never_cache
def resolve(request,model_name):
    from django.http import JsonResponse
    from .models import normalize_location
    if model_name not in NAMES:raise Http404
    model=apps.get_model('crm',model_name)
    if not request.user.has_perm('crm.change_'+model_name):raise PermissionDenied
    target=normalize_location(request.GET.get('value','')[:250]);mode=request.GET.get('mode','text')
    column='code' if mode=='code' and hasattr(model,'code') else 'name'
    found=[pk for pk,value in model.objects.values_list('pk',column) if normalize_location(value)==target][:2]
    return JsonResponse({'id':str(found[0]) if len(found)==1 else None})
