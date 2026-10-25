from decimal import Decimal
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django import forms
from .models import Contract, Task, AuditEvent, Payment, Customer, PaymentMethod

@login_required
@permission_required('crm.view_contract',raise_exception=True)
def contracts(request):
    from .contract_journal import journal_context
    if 'reset' in request.GET:
        request.session.pop('contract_journal',None)
        return redirect('contracts')
    if not request.GET and request.session.get('contract_journal'):
        return redirect('/?'+request.session['contract_journal'])
    context=journal_context(request.GET,DateRange)
    if context['dateform'].is_valid():
        from .contract_journal import COLUMNS
        allowed={'customer','email','phone','number','operator','country','start','end','sort'}|{'f_'+key for key,_ in COLUMNS}
        saved=request.GET.copy()
        for key in list(saved):
            if key not in allowed:del saved[key]
        saved['start']=context['start_value'];saved['end']=context['end_value']
        for key in list(saved):
            if not any(saved.getlist(key)):del saved[key]
        request.session['contract_journal']=saved.urlencode()
    return render(request,'crm/contracts.html',context)

class DateRange(forms.Form):
    start=forms.DateField(required=False)
    end=forms.DateField(required=False)

@login_required
@permission_required('crm.change_task',raise_exception=True)
@require_POST
@transaction.atomic
def reschedule(request):
    f=forms.DateField()
    try:
        due=f.clean(request.POST.get('due'))
        ids=[int(v) for v in request.POST.getlist('tasks')]
    except (forms.ValidationError,ValueError):return HttpResponseBadRequest('Проверьте дату и выбранные задачи')
    for task in Task.objects.select_for_update().filter(pk__in=ids,done=False):
        old=task.due
        task.due=due;task.save(update_fields=['due'])
        AuditEvent.objects.create(actor=request.user,object_type='crm.Task',object_id=str(task.pk),action='rescheduled',changes={'due':{'old':str(old),'new':str(due)}})
    return redirect('tasks')
