import io
import json
from django import forms
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse,FileResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from .update_views import require_admin
from .legacy_history_jobs import state,start_job
from .legacy_history import MAX_PACKAGE
from .models import LegacyImportRun,LegacyRecord

class HistoryPackageForm(forms.Form):
    package=forms.FileField(label='Подготовленный ZIP истории',widget=forms.FileInput(attrs={'accept':'.zip'}))
    confirmed=forms.BooleanField(label='Это тренировочная загрузка: суммы в рублях, итог из шапки; неразнесённые платежи остаются в отчёте. Существующие данные не удаляются.')
    def clean_package(self):
        value=self.cleaned_data['package']
        if value.size>MAX_PACKAGE:raise forms.ValidationError('Пакет должен быть не больше 8 МБ.')
        return value

@login_required
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def page(request):
    require_admin(request.user)
    form=HistoryPackageForm(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        try:start_job(form.cleaned_data['package'],request.user)
        except (ValueError,OSError):form.add_error(None,'Не удалось запустить загрузку. Проверьте её состояние и свободное место на сервере.')
        else:return redirect('legacy_history')
    return render(request,'crm/legacy_history.html',{'form':form,'job':state(),'runs':LegacyImportRun.objects.filter(section='history')[:10]})

@login_required
@never_cache
def status(request):
    require_admin(request.user);return JsonResponse(state())

@login_required
@never_cache
def report(request,pk):
    require_admin(request.user);run=get_object_or_404(LegacyImportRun,pk=pk,section='history')
    payload={'source':run.source_key,'snapshot':run.source_snapshot,'summary':run.summary,'issues':run.issues,'deferred_payments':[r.payload for r in run.records.filter(table='LIST_MANYS',status='deferred')]}
    return FileResponse(io.BytesIO(json.dumps(payload,ensure_ascii=False,indent=2).encode()),as_attachment=True,filename=f'legacy-report-{run.pk}.json',content_type='application/json')

@login_required
@never_cache
def source(request,pk):
    require_admin(request.user);record=get_object_or_404(LegacyRecord,pk=pk)
    payload={'table':record.table,'source_id':record.source_id,'fields':record.payload}
    response=FileResponse(io.BytesIO(json.dumps(payload,ensure_ascii=False,indent=2).encode()),as_attachment=True,filename=f'legacy-source-{record.pk}.json',content_type='application/json')
    response['X-Content-Type-Options']='nosniff';return response
