import io
import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse,Http404
from django.shortcuts import get_object_or_404,redirect,render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET,require_POST
from django.views.decorators.debug import sensitive_post_parameters
from . import eta_transport,eta_mail
from .eta_views import require,app_for
from .models import Contract,ETAApplication,ETAOfficialNotice


@login_required
@never_cache
@require_POST
@sensitive_post_parameters()
def enqueue(request,pk):
    require(request.user,'crm.change_etaapplication','crm.add_etaexport','crm.view_etaexport')
    contract=get_object_or_404(Contract,pk=pk)
    try:
        ids=[uuid.UUID(v) for v in request.POST.getlist('applications')]
        eta_transport.enqueue(contract,ids,request.user)
        messages.success(request,'Готовые задания переданы в фоновую очередь. Сводка исполнителя появится здесь.')
    except (ValidationError,ValueError) as exc:messages.error(request,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Некорректный выбор.')
    return redirect('eta_page',pk=pk)


@login_required
@never_cache
@require_POST
def resume(request,pk,application_id):
    require(request.user,'crm.change_etaapplication')
    app=app_for(get_object_or_404(Contract,pk=pk),application_id)
    try:
        if request.POST.get('action')=='status':eta_transport.schedule_status(app,request.user)
        else:eta_transport.resume(app,request.user)
        messages.success(request,'Задание поставлено в очередь. Новая заявка на портале не создаётся при проверке статуса.')
    except ValidationError as exc:messages.error(request,' '.join(exc.messages))
    return redirect('eta_detail',pk=pk,application_id=application_id)


@login_required
@never_cache
@require_GET
def notices(request):
    require(request.user)
    rows=ETAOfficialNotice.objects.filter(accepted_at=None).select_related('application__tourist').defer('original').order_by('-received_at')[:100]
    return render(request,'crm/eta/notices.html',{'notices':rows})


@login_required
@never_cache
@require_GET
def notice(request,notice_id):
    require(request.user)
    item=get_object_or_404(ETAOfficialNotice.objects.select_related('application__tourist').defer('original'),pk=notice_id)
    return render(request,'crm/eta/notice.html',{'notice':item})


@login_required
@never_cache
@require_POST
def accept_notice(request,notice_id):
    require(request.user,'crm.change_etaapplication')
    item=get_object_or_404(ETAOfficialNotice,pk=notice_id)
    try:
        if request.POST.get('verified')!='on':raise ValidationError('Проверьте оригинал, подлинность и данные основного заявителя.')
        eta_mail.accept_notice(item,request.user)
        messages.success(request,'Официальное письмо проверено и сохранено в задании туриста.')
    except ValidationError as exc:messages.error(request,' '.join(exc.messages))
    return redirect('eta_notice',notice_id=notice_id)


@login_required
@never_cache
@require_GET
def document(request,notice_id,kind):
    require(request.user)
    item=get_object_or_404(ETAOfficialNotice,pk=notice_id)
    if kind=='eml':content=bytes(item.original);mime='message/rfc822'
    elif kind=='pdf':
        try:content=eta_mail.pdf_copy(item)
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages));return redirect('eta_notice',notice_id=notice_id)
        mime='application/pdf'
    else:raise Http404
    response=FileResponse(io.BytesIO(content),as_attachment=True,filename=f'eta-notice-{item.pk}.{kind}',content_type=mime)
    response['X-Content-Type-Options']='nosniff';response['Content-Security-Policy']="default-src 'none'; sandbox";return response


@login_required
@never_cache
@require_GET
def tourist_notices(request,tourist_id):
    require(request.user)
    from .models import Tourist
    tourist=get_object_or_404(Tourist,pk=tourist_id)
    applications=ETAApplication.objects.filter(tourist=tourist).select_related('contract').prefetch_related('official_notices').defer('approval_notice')
    return render(request,'crm/eta/tourist.html',{'tourist':tourist,'applications':applications})
