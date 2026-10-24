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
@permission_required('crm.view_task',raise_exception=True)
def tasks(request):
    today=timezone.localdate()
    qs=Task.objects.select_related('customer','contract__operator','operator','employee').prefetch_related('contract__bookings')
    mode=request.GET.get('period','today')
    if mode=='done':qs=qs.filter(done=True)
    elif mode!='all':
        qs=qs.filter(done=False)
        if mode=='overdue':qs=qs.filter(due__lt=today)
        elif mode=='future':qs=qs.filter(due__gt=today)
        elif mode=='today':qs=qs.filter(due=today)
    f=DateRange(request.GET)
    if f.is_valid():
        if f.cleaned_data['start']:qs=qs.filter(due__gte=f.cleaned_data['start'])
        if f.cleaned_data['end']:qs=qs.filter(due__lte=f.cleaned_data['end'])
    return render(request,'crm/tasks.html',{'rows':qs,'dateform':f,'period':mode})

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


@login_required
@permission_required('crm.view_payment',raise_exception=True)
def finances(request):
    qs=Payment.objects.select_related('contract__customer','contract__operator','method').order_by('-date','-pk')
    for param,lookup in [('customer','contract__customer__name__icontains'),('number','contract__number__icontains'),('operator','contract__operator__name__icontains'),('method','method__name__icontains')]:
        if request.GET.get(param):qs=qs.filter(**{lookup:request.GET[param]})
    kind=request.GET.get('kind')
    if kind in dict(Payment.KINDS):qs=qs.filter(kind=kind)
    f=DateRange(request.GET)
    if f.is_valid():
        if f.cleaned_data['start']:qs=qs.filter(date__gte=f.cleaned_data['start'])
        if f.cleaned_data['end']:qs=qs.filter(date__lte=f.cleaned_data['end'])
    rows=list(qs)
    incoming=outgoing=Decimal('0')
    for payment in rows:
        payment.incoming=payment.amount if payment.kind in ('customer','operator_refund') else Decimal('0')
        payment.outgoing=payment.amount if payment.kind in ('operator','customer_refund') else Decimal('0')
        incoming+=payment.incoming;outgoing+=payment.outgoing
    from .models import payment_operation_choices
    return render(request,'crm/finances.html',{'rows':rows,'count':len(rows),'incoming':incoming,'outgoing':outgoing,'balance':incoming-outgoing,'dateform':f,'kinds':payment_operation_choices()})
