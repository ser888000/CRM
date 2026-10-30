import io
import json
from datetime import date
from decimal import Decimal
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404,JsonResponse,FileResponse
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from django.views.decorators.http import require_GET,require_POST,require_http_methods
from .models import Contract,ETAApplication,ETAExport,AuditEvent
from . import eta
from .eta_forms import ETAPreparationForm,ETAAnswerSet,ETAResultForm,ETAAuthorizeForm,ETAReturnForm


def invalid_json_constant(value):
    raise ValueError('Non-finite JSON number')


def require(user,*perms):
    from django.core.exceptions import PermissionDenied
    if not user.has_perms((*eta.READ_PERMS,*perms)):raise PermissionDenied


def app_for(contract,pk,lock=False):
    qs=ETAApplication.objects.select_related('tourist','contract').defer('approval_notice')
    if lock:qs=qs.select_for_update()
    return get_object_or_404(qs,pk=pk,contract=contract)


def json_download(payload,name):
    response=JsonResponse(payload,json_dumps_params={'ensure_ascii':False,'indent':2})
    response['Content-Disposition']=f'attachment; filename="{name}"'
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    return response


@login_required
@never_cache
@require_http_methods(['GET','POST'])
@sensitive_post_parameters()
@transaction.atomic
def page(request,pk):
    require(request.user)
    contract=get_object_or_404(Contract.objects.select_related('customer').select_for_update(),pk=pk)
    class Selection(forms.Form):
        tourists=forms.ModelMultipleChoiceField(label='Туристы договора',queryset=eta.linked(contract),widget=forms.CheckboxSelectMultiple)
    form=Selection(request.POST if request.method=='POST' else None)
    if request.method=='POST':
        require(request.user,'crm.add_etaapplication','crm.change_etaapplication')
        if form.is_valid():
            if len(form.cleaned_data['tourists'])>50:form.add_error('tourists','Выберите не более 50 туристов.')
            else:
                for tourist in form.cleaned_data['tourists']:
                    app,created=ETAApplication.objects.get_or_create(contract=contract,tourist=tourist)
                    if created:AuditEvent.objects.create(actor=request.user,object_type='crm.ETAApplication',object_id=str(app.pk),action='eta_created',changes={})
                return redirect('eta_page',pk=pk)
    applications=list(ETAApplication.objects.filter(contract=contract).select_related('tourist','contract').defer('approval_notice').order_by('tourist_id'))
    for app in applications:
        app.issues=eta.assess(app) if not app.active_export_id else []
        app.source_changed=app.source_hash!=eta.source_hash(contract,app.tourist) if app.source_hash else False
    batches=ETAExport.objects.filter(contract=contract).defer('payload').order_by('-created_at')[:30]
    return render(request,'crm/eta/page.html',{'contract':contract,'selection_form':form,'applications':applications,'batches':batches,'result_form':ETAResultForm(),'has_tourists':eta.linked(contract).exists(),'executor_enabled':settings.ETA_EXECUTOR_ENABLED})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
@sensitive_post_parameters()
@sensitive_variables()
@transaction.atomic
def prepare(request,pk,application_id):
    require(request.user,'crm.change_etaapplication')
    contract=get_object_or_404(Contract.objects.select_related('customer'),pk=pk)
    app=app_for(contract,application_id,True)
    if not eta.linked(contract).filter(pk=app.tourist_id).exists():raise Http404
    if app.active_export_id:
        messages.info(request,'Задание уже передано. Для исправлений сначала проверьте на портале отсутствие принятой заявки и верните задание на подготовку.')
        return redirect('eta_detail',pk=pk,application_id=app.pk)
    current_hash=eta.source_hash(contract,app.tourist)
    source=eta.initial_data(contract,app.tourist)
    initial=dict(source);initial.update(app.preparation)
    changed=bool(app.source_hash and app.source_hash!=current_hash)
    if changed:
        # CRM is authoritative. Agency defaults are not new facts about a person.
        initial.update({key:value for key,value in source.items() if key not in ('travel_last_14_days','own_passport')})
        if app.preparation.get('hotel_name')!=source.get('hotel_name'):
            initial['hotel_address']=source.get('hotel_address','')
        if app.preparation.get('home_address')!=source.get('home_address'):
            initial.update(home_city='',home_region='',home_country='')
        initial.update({key:False for key in ('identity_confirmed','travel_confirmed','previous_visas_confirmed','travel_history_confirmed','portal_rules_checked')})
    answers=app.preparation.get('answers') or [{'question':'Covid Vaccination Status','answer':'Yes','confirmed':False}]
    if changed:answers=[{**row,'confirmed':False} for row in answers]
    form=ETAPreparationForm(request.POST if request.method=='POST' else None,initial=initial,contract=contract,tourist=app.tourist)
    answer_set=ETAAnswerSet(request.POST if request.method=='POST' else None,initial=answers,prefix='answers')
    if request.method=='POST' and form.is_valid() and answer_set.is_valid():
        if request.POST.get('source_hash')!=current_hash:form.add_error(None,'Данные CRM обновились после открытия формы. Обновите страницу: будут подставлены актуальные сведения.')
        elif request.POST.get('version')!=str(app.updated_at):form.add_error(None,'Задание изменилось в другом окне. Обновите страницу.')
        else:
            values={}
            for key,value in form.cleaned_data.items():
                if isinstance(value,date):value=value.isoformat()
                elif isinstance(value,Decimal):value=str(value)
                elif hasattr(value,'pk'):value=value.pk
                values[key]=value
            values['own_passport']='yes'
            values['answers']=[{k:row.get(k) for k in ('question','answer','confirmed')} for row in answer_set.cleaned_data if not row.get('DELETE') and (row.get('question') or row.get('answer'))]
            values['confirmed_by']=request.user.pk;values['confirmed_at']=timezone.now().isoformat()
            app.preparation=values;app.source_hash=current_hash
            issues=eta.assess(app);app.status='needs_data' if issues else 'ready';app.save()
            AuditEvent.objects.create(actor=request.user,object_type='crm.ETAApplication',object_id=str(app.pk),action='eta_prepared',changes={'status':app.status,'fields':sorted(form.cleaned_data)})
            messages.success(request,'Подготовка сохранена. '+('Остались пропуски: '+str(len(issues)) if issues else 'Готово к экспорту задания.'))
            return redirect('eta_prepare',pk=pk,application_id=app.pk)
    groups=[('Турист',['surname','given_names','gender','birthday','nationality','birth_country','child_occupation']),
        ('Паспорт',['passport_type','passport_number','passport_issued','passport_expires','identity_confirmed']),
        ('Адрес и телефон заказчика',['home_address','home_city','home_region','home_country','phone']),
        ('Прибытие и проживание',['arrival_date','departure_date','departure_airport','arrival_airport','airline','flight_number','hotel_name','hotel_address','travel_confirmed']),
        ('Подтверждённые сведения',['previous_visas','previous_visas_confirmed','travel_last_14_days','travel_history_confirmed','portal_rules_checked']),
        ('Дети и представитель',['parent_tourist','relationship','guardian_details']),
        ('Ожидаемый сбор',['expected_fee','expected_fee_currency'])]
    return render(request,'crm/eta/prepare.html',{'contract':contract,'application':app,'form':form,'answers':answer_set,
        'issues':eta.assess(app),'source_changed':changed,'source_hash':current_hash,'version':str(app.updated_at),'email':eta.EMAIL,'field_groups':[(title,[form[key] for key in keys]) for title,keys in groups]})


@login_required
@never_cache
@require_POST
@sensitive_post_parameters()
def export(request,pk):
    require(request.user,'crm.change_etaapplication','crm.add_etaexport','crm.view_etaexport')
    contract=get_object_or_404(Contract,pk=pk)
    ids=request.POST.getlist('applications')
    try:
        import uuid
        ids=[uuid.UUID(key) for key in ids]
        batch=eta.export_applications(contract,ids,request.user)
        return json_download(batch.payload,f'eta-job-{batch.pk}.json')
    except (ValidationError,ValueError,TypeError) as exc:
        messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Некорректный выбор заданий.')
        return redirect('eta_page',pk=pk)


@login_required
@never_cache
@require_GET
def download_export(request,pk,batch_id):
    require(request.user,'crm.view_etaexport')
    batch=get_object_or_404(ETAExport,pk=batch_id,contract_id=pk)
    return json_download(batch.payload,f'eta-job-{batch.pk}.json')


@login_required
@never_cache
@require_POST
@sensitive_post_parameters()
@sensitive_variables()
def import_result(request,pk):
    require(request.user,'crm.change_etaapplication')
    contract=get_object_or_404(Contract,pk=pk)
    form=ETAResultForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            content=form.cleaned_data['result_file'].read(16*1024*1024+1)
            if len(content)>16*1024*1024:raise ValidationError('Превышен размер JSON.')
            payload=json.loads(content,parse_constant=invalid_json_constant)
            count=eta.import_results(contract,payload,request.user)
            messages.success(request,f'Результат принят. Обновлено заданий: {count}.')
        except ValidationError as exc:messages.error(request,' '.join(exc.messages))
        except (ValueError,TypeError,UnicodeError,RecursionError,KeyError):messages.error(request,'Некорректный JSON результата. Изменения не применены.')
    else:messages.error(request,'Выберите JSON до 16 МБ и подтвердите проверку результатов.')
    return redirect('eta_page',pk=pk)


@login_required
@never_cache
@require_GET
def detail(request,pk,application_id):
    require(request.user)
    contract=get_object_or_404(Contract,pk=pk);app=app_for(contract,application_id)
    issues=eta.review_issues(app) if app.status=='awaiting_confirmation' else []
    return render(request,'crm/eta/detail.html',{'contract':contract,'application':app,'review_issues':issues,
        'summary':json.dumps(app.result.get('portal_summary',{}),ensure_ascii=False,indent=2),
        'authorize_form':ETAAuthorizeForm(initial={'version':str(app.updated_at),'fee':app.actual_fee,'currency':app.fee_currency}),
        'return_form':ETAReturnForm(initial={'version':str(app.updated_at)}),'can_return':bool(app.active_export_id and not app.application_number and app.status not in eta.SENT and app.transport_state!='leased' and not app.submission_started_at)})


@login_required
@never_cache
@require_POST
@sensitive_post_parameters()
@transaction.atomic
def authorize(request,pk,application_id):
    require(request.user,'crm.change_etaapplication')
    contract=get_object_or_404(Contract,pk=pk);app=app_for(contract,application_id,True)
    form=ETAAuthorizeForm(request.POST)
    issues=eta.review_issues(app) if app.status=='awaiting_confirmation' else ['Задание не ожидает подтверждения.']
    if app.submission_started_at or app.application_number:issues.append('Подача уже начата. Повторное подтверждение и отправка запрещены; проверьте статус.')
    if form.is_valid() and not issues:
        if form.cleaned_data['version']!=str(app.updated_at) or app.source_hash!=eta.source_hash(contract,app.tourist):messages.error(request,'Сведения изменились. Проверьте актуальную сводку заново.')
        elif form.cleaned_data['fee']!=app.actual_fee or form.cleaned_data['currency']!=app.fee_currency:messages.error(request,'Сумма/валюта не совпадают с фактической сводкой.')
        else:
            app.submission_authorized_at=timezone.now();app.submission_authorized_by=request.user
            app.authorization={};app.authorization=eta.authorization_context(app);app.save()
            AuditEvent.objects.create(actor=request.user,object_type='crm.ETAApplication',object_id=str(app.pk),action='eta_submission_authorized',changes={'summary_verified':True})
            if app.transport_state=='waiting' and app.worker_id:
                app.transport_state='queued';app.transport_action='submit';app.next_check_at=None;app.save()
                messages.success(request,'Подача подтверждена. Исполнитель продолжит сохранённую сессию после повторной проверки разрешения.')
            else:messages.success(request,'Подача подтверждена. Для резервного файлового исполнителя доступно разрешение в разделе обмена файлами.')
    else:messages.error(request,'Подтверждение не принято: '+(' '.join(issues) if issues else 'подтвердите сводку, условия и фактический сбор.'))
    return redirect('eta_detail',pk=pk,application_id=app.pk)


@login_required
@never_cache
@require_GET
def download_authorization(request,pk,application_id):
    require(request.user,'crm.change_etaapplication')
    app=app_for(get_object_or_404(Contract,pk=pk),application_id)
    try:return json_download(eta.authorization_payload(app),f'eta-authorization-{app.pk}.json')
    except ValidationError:raise Http404


@login_required
@never_cache
@require_POST
@sensitive_post_parameters()
@transaction.atomic
def return_to_prepare(request,pk,application_id):
    require(request.user,'crm.change_etaapplication')
    app=app_for(get_object_or_404(Contract,pk=pk),application_id,True)
    form=ETAReturnForm(request.POST)
    if form.is_valid() and form.cleaned_data['version']==str(app.updated_at) and app.status not in eta.SENT and not app.application_number and app.transport_state!='leased' and not app.submission_started_at:
        app.transport_state='manual';app.worker_id='';app.lease_sha256='';app.lease_until=None;app.submission_started_at=None;app.active_export=None;app.active_identity_key=None;app.status='needs_data';app.submission_authorized_at=None;app.submission_authorized_by=None;app.authorization={}
        for key in ('identity_confirmed','travel_confirmed','previous_visas_confirmed','travel_history_confirmed','portal_rules_checked'):app.preparation[key]=False
        app.preparation['answers']=[{**row,'confirmed':False} for row in app.preparation.get('answers',[])]
        app.save()
        AuditEvent.objects.create(actor=request.user,object_type='crm.ETAApplication',object_id=str(app.pk),action='eta_returned_to_prepare',changes={'portal_checked_no_submission':True})
        messages.success(request,'Задание возвращено. Старые пакеты результатов и разрешения больше не действуют.')
        return redirect('eta_prepare',pk=pk,application_id=app.pk)
    messages.error(request,'Возврат запрещён: проверьте версию, отсутствие принятой заявки и подтвердите проверку портала. Поданные заявления повторно не запускаются.')
    return redirect('eta_detail',pk=pk,application_id=app.pk)


@login_required
@never_cache
@require_GET
def approval(request,pk,application_id):
    require(request.user)
    app=get_object_or_404(ETAApplication,pk=application_id,contract_id=pk,status='approved')
    if not app.approval_notice:raise Http404
    response=FileResponse(io.BytesIO(bytes(app.approval_notice)),as_attachment=True,filename=f'eta-{app.pk}.pdf',content_type='application/pdf')
    response['X-Content-Type-Options']='nosniff';return response


def simple_download_payload(contract,tourists):
    rows=[];hotel_name=contract.hotel
    for tourist in tourists:
        data=eta.initial_data(contract,tourist)
        hotel_name=data.get('hotel_name','')
        rows.append({
            'surname':data.get('surname',''),'given_names':data.get('given_names',''),
            'gender':data.get('gender',''),'birth_date':data.get('birthday',''),
            'nationality':data.get('nationality',''),'birth_country':data.get('birth_country',''),
            'passport_number':data.get('passport_number',''),'passport_issued':data.get('passport_issued',''),
            'passport_expires':data.get('passport_expires',''),
            'home_address':data.get('home_address',''),'phone':data.get('phone',''),
        })
    flights=contract.source_data.get('transport',[])
    flights=flights if isinstance(flights,list) else []
    airports=('CMB','HRI','JAF')
    outbound=[f for f in flights if isinstance(f,dict) and str(f.get('terminalcodeto','')).upper() in airports]
    inbound=[f for f in flights if isinstance(f,dict) and str(f.get('terminalcodefrom','')).upper() in airports]
    def flight_data(matches):
        f=matches[0] if len(matches)==1 else {}
        return {'departure_date':eta.source_date(f.get('datefrom')),'arrival_date':eta.source_date(f.get('dateto')),
                'departure_airport':f.get('terminalcodefrom') or '', 'airline':f.get('aircompany') or '',
                'flight_number':f.get('number') or ''}
    return {'hotel':{'name':hotel_name,'address':''},'flight':flight_data(outbound),
            'return_flight':flight_data(inbound),'tourists':rows}


@login_required
@never_cache
@require_GET
@sensitive_variables()
def simple_tourist_download(request,pk,tourist_id):
    """Read-only handoff for one linked tourist; no application or readiness checks."""
    require(request.user)
    contract=get_object_or_404(Contract.objects.select_related('customer'),pk=pk)
    tourist=get_object_or_404(eta.linked(contract),pk=tourist_id)
    return json_download(simple_download_payload(contract,[tourist]),f'eta-tourist-{contract.pk}-{tourist.pk}.json')


@login_required
@never_cache
@require_POST
@sensitive_post_parameters()
@sensitive_variables()
def simple_selected_download(request,pk):
    require(request.user)
    contract=get_object_or_404(Contract.objects.select_related('customer'),pk=pk)
    # Only membership is checked; incomplete passport/travel data never blocks export.
    field=forms.ModelMultipleChoiceField(queryset=eta.linked(contract))
    try:tourists=list(field.clean(request.POST.getlist('tourists')))
    except ValidationError:
        messages.error(request,'Отметьте туристов этого договора для скачивания JSON.')
        return redirect('eta_page',pk=pk)
    return json_download(simple_download_payload(contract,tourists),f'eta-tourists-{contract.pk}.json')
