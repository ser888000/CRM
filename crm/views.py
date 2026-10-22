from decimal import Decimal
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django import forms
from .models import Contract, Task, AuditEvent

@login_required
@permission_required('crm.view_contract',raise_exception=True)
def contracts(request):
    qs=Contract.objects.select_related('customer','operator').order_by('-date','-pk')
    for param,lookup in [('customer','customer__name__icontains'),('operator','operator__name__icontains'),('country','country__icontains'),('number','number__icontains')]:
        if request.GET.get(param): qs=qs.filter(**{lookup:request.GET[param]})
    dateform=DateRange(request.GET)
    if dateform.is_valid():
        if dateform.cleaned_data['start']:qs=qs.filter(date__gte=dateform.cleaned_data['start'])
        if dateform.cleaned_data['end']:qs=qs.filter(date__lte=dateform.cleaned_data['end'])
    rows=list(qs)
    totals={k:sum((getattr(c,k) for c in rows),Decimal('0')) for k in ['amount','paid','cost','profit','debt']}
    return render(request,'crm/contracts.html',{'rows':rows,'totals':totals,'dateform':dateform})
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
    else:
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
