"""Server-only scoped bearer endpoints. Never authenticate with query strings."""
import base64
import json
import re
import secrets
from functools import wraps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables,sensitive_post_parameters
from django.views.decorators.http import require_POST
from . import eta_transport
from .models import ETAApplication


def endpoint(role):
    def decorate(fn):
        @csrf_exempt
        @require_POST
        @sensitive_variables()
        @sensitive_post_parameters()
        @wraps(fn)
        def wrapped(request,*args,**kwargs):
            configured=getattr(settings,'ETA_'+role.upper()+'_TOKEN','')
            supplied=request.headers.get('Authorization','')
            if len(configured)<32 or not secrets.compare_digest(supplied.encode(),('Bearer '+configured).encode()):return JsonResponse({'error':'unauthorized'},status=401)
            if role=='worker' and not settings.ETA_EXECUTOR_ENABLED:return JsonResponse({'error':'executor_disabled'},status=503)
            try:
                if int(request.META.get('CONTENT_LENGTH') or 0)>(3 if role=='mail' else 12)*1024*1024:raise ValidationError('Слишком большой запрос.')
                body=json.loads(request.body,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                if not isinstance(body,dict):raise ValueError()
                if role=='worker' and not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',body.get('worker_id','')):raise ValidationError('Нужен идентификатор исполнителя.')
                response=JsonResponse(fn(body,*args,**kwargs));response['Cache-Control']='no-store';return response
            except (ValidationError,ValueError,TypeError,KeyError,ETAApplication.DoesNotExist) as exc:
                message=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Некорректный запрос.'
                return JsonResponse({'error':message},status=409)
        return wrapped
    return decorate


@endpoint('worker')
def claim(body):
    sessions=body.get('retained_sessions',[])
    if not isinstance(sessions,list) or len(sessions)>50 or any(not isinstance(s,str) for s in sessions) or type(body.get('capacity',True)) is not bool:raise ValidationError('Некорректная ёмкость исполнителя.')
    return {'job':eta_transport.claim(body['worker_id'],sessions,body.get('capacity',True))}

@endpoint('worker')
def heartbeat(body,application_id):
    eta_transport.heartbeat(application_id,body['worker_id'],body['lease_token']);return {'ok':True}

@endpoint('worker')
def begin(body,application_id):
    return {'authorization':eta_transport.begin_submission(application_id,body['worker_id'],body['lease_token'],body['review_sha256'],body['conditions_sha256'],body['fee'])}

@endpoint('worker')
def result(body,application_id):
    eta_transport.receive_result(application_id,body['worker_id'],body['lease_token'],body['result']);return {'ok':True}

@endpoint('mail')
def mail(body):
    from .eta_mail import ingest
    try:raw=base64.b64decode(body['eml_base64'],validate=True)
    except (ValueError,TypeError):raise ValidationError('Некорректный EML.') from None
    notice=ingest(raw)
    return {'notice_id':str(notice.pk),'accepted':bool(notice.accepted_at),'review_required':not bool(notice.accepted_at)}


@endpoint('worker')
def sessions(body):
    keys=body.get('applications',[])
    if not isinstance(keys,list) or len(keys)>50:raise ValidationError('Некорректный список сессий.')
    import uuid
    try:keys=[uuid.UUID(key) for key in keys]
    except (ValueError,TypeError,AttributeError):raise ValidationError('Некорректные идентификаторы.') from None
    keep=ETAApplication.objects.filter(pk__in=keys,worker_id=body['worker_id'],active_export__isnull=False,transport_state__in=('waiting','stopped','queued','leased')).exclude(status='approved').values_list('pk',flat=True)
    return {'keep':[str(key) for key in keep]}
