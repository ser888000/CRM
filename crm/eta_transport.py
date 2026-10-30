"""Leases and one-use submission fence for existing ETAApplication / v1 batches."""
import hashlib
import secrets
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from . import eta
from .models import ETAApplication, AuditEvent


def audit(app,action,actor=None):
    AuditEvent.objects.create(actor=actor,object_type='crm.ETAApplication',object_id=str(app.pk),action=action,changes={'transport':app.transport_state,'action':app.transport_action})


@transaction.atomic
def enqueue(contract,ids,actor):
    if not settings.ETA_EXECUTOR_ENABLED:raise ValidationError('Исполнитель ETA ещё не подключён. Доступен резервный обмен файлами.')
    batch=eta.export_applications(contract,ids,actor)
    for app in ETAApplication.objects.select_for_update().filter(contract=contract,pk__in=ids):
        if app.transport_state!='manual':continue  # repeated button never restarts a session
        if app.status!='ready' or app.application_number:raise ValidationError('Поданное или незавершённое задание нельзя запустить заново.')
        app.transport_state='queued';app.transport_action='prepare';app.save();audit(app,'eta_queued',actor)
    return batch


def expire_leases():
    # Lost prepare/status work is stopped; lost submission is always uncertain.
    for app in ETAApplication.objects.filter(transport_state='leased',lease_until__lt=timezone.now()).only('pk','lease_until','transport_action'):
        reason='Связь с исполнителем потеряна. Проверьте сохранённую сессию; автоматического повтора нет.'
        if app.transport_action=='submit':reason='Результат подачи неизвестен. Сначала проверьте статус принятого заявления; повторная подача запрещена.'
        values={'transport_state':'stopped','stop_reason':reason,'lease_sha256':'','lease_until':None}
        if app.transport_action=='submit':values.update(transport_state='queued',transport_action='status',next_check_at=timezone.now())
        ETAApplication.objects.filter(pk=app.pk,transport_state='leased',lease_until=app.lease_until).update(**values)


@transaction.atomic
def claim(worker,retained_sessions=None,capacity=True):
    expire_leases()
    now=timezone.now()
    from django.db.models import Q
    candidates=ETAApplication.objects.select_for_update().filter(transport_state='queued').filter(Q(worker_id='')|Q(worker_id=worker)).filter(Q(next_check_at=None)|Q(next_check_at__lte=now)).select_related('active_export').order_by('updated_at')
    for app in candidates:
        if not capacity and app.transport_action=='prepare' and str(app.pk) not in (retained_sessions or []):continue
        if not app.active_export_id:continue
        token=secrets.token_urlsafe(32);hashed=hashlib.sha256(token.encode()).hexdigest()
        updated=ETAApplication.objects.filter(pk=app.pk,transport_state='queued').update(transport_state='leased',worker_id=worker,lease_sha256=hashed,lease_until=now+timedelta(minutes=5))
        if not updated:continue
        app.refresh_from_db()
        if app.transport_action=='prepare' and app.status in ('ready','needs_data','error','awaiting_confirmation'):
            app.status='filling';app.save(update_fields=['status','updated_at'])
        entry=next(row for row in app.active_export.payload['applicants'] if row['application_id']==str(app.pk))
        packet={**app.active_export.payload,'applicants':[entry]}
        return {'application_id':str(app.pk),'lease_token':token,'action':app.transport_action,'packet':packet,
                'current_result':app.result,'application_number':app.application_number,
                'submission_started':bool(app.submission_started_at),'authorization':eta.authorization_payload(app) if app.transport_action=='status' and app.submission_authorized_at else None}
    return None


def leased(application_id,worker,token):
    app=ETAApplication.objects.select_for_update().select_related('contract','tourist','active_export').get(pk=application_id)
    if not isinstance(token,str) or app.transport_state!='leased' or app.worker_id!=worker or not app.lease_until or app.lease_until<timezone.now() or not secrets.compare_digest(app.lease_sha256,hashlib.sha256(token.encode()).hexdigest()):
        raise ValidationError('Аренда задания истекла или принадлежит другому исполнителю.')
    return app


@transaction.atomic
def heartbeat(application_id,worker,token):
    app=leased(application_id,worker,token)
    app.lease_until=timezone.now()+timedelta(minutes=5);app.save(update_fields=['lease_until'])


@transaction.atomic
def begin_submission(application_id,worker,token,review_sha256,conditions_sha256,fee):
    app=leased(application_id,worker,token)
    if app.transport_action!='submit' or app.status!='awaiting_confirmation' or app.submission_started_at or app.application_number:
        raise ValidationError('Подача уже начата либо задание не готово. Автоматический повтор запрещён.')
    if not app.submission_authorized_at or app.source_hash!=eta.source_hash(app.contract,app.tourist) or eta.review_issues(app):
        raise ValidationError('Разрешение отозвано или данные/условия требуют новой проверки.')
    context=eta.authorization_context(app)
    if review_sha256!=context['review_sha256'] or conditions_sha256!=context['conditions_sha256'] or fee!={'amount':context['fee'],'currency':context['currency']}:
        raise ValidationError('Сводка или условия изменились после подтверждения.')
    app.submission_started_at=timezone.now();app.save(update_fields=['submission_started_at'])
    audit(app,'eta_submission_started')
    return eta.authorization_payload(app)


@transaction.atomic
def receive_result(application_id,worker,token,payload):
    app=leased(application_id,worker,token)
    rows=payload.get('results') if isinstance(payload,dict) else None
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict) or rows[0].get('application_id')!=str(app.pk):raise ValidationError('Результат не соответствует арендованному заданию.')
    row=rows[0]
    if app.status=='approved' and row.get('stage')!='approved':
        app.lease_sha256='';app.lease_until=None;app.transport_state='completed';app.save();return
    if row.get('stage')=='submitted' and not app.submission_started_at:raise ValidationError('Подача не была разрешена активным исполнителем.')
    if app.submission_started_at and app.status=='awaiting_confirmation' and row.get('stage') in ('under_review','approved'):
        app.status='error';app.save(update_fields=['status'])  # recovered receipt after uncertain final click
    eta.import_results(app.contract,payload,None)
    app.refresh_from_db()
    app.lease_sha256='';app.lease_until=None
    if app.status in ('submitted','under_review'):
        app.transport_state='queued';app.transport_action='status';app.next_check_at=timezone.now()+timedelta(minutes=10)
    elif app.status=='approved':app.transport_state='completed'
    elif app.status=='awaiting_confirmation':app.transport_state='waiting'
    else:app.transport_state='stopped'
    app.save();audit(app,'eta_executor_result')


@transaction.atomic
def resume(app,actor):
    app=ETAApplication.objects.select_for_update().get(pk=app.pk)
    if not app.active_export_id or not app.worker_id or app.transport_state not in ('stopped','waiting') or app.submission_started_at or app.application_number:
        raise ValidationError('Возобновление заполнения запрещено. После начала подачи доступна только проверка статуса.')
    app.transport_state='queued';app.transport_action='prepare';app.stop_reason='';app.submission_authorized_at=None;app.authorization={};app.save();audit(app,'eta_resumed',actor)


@transaction.atomic
def schedule_status(app,actor):
    app=ETAApplication.objects.select_for_update().get(pk=app.pk)
    if not app.active_export_id or not app.worker_id or app.transport_state=='leased' or not (app.application_number or app.submission_started_at):raise ValidationError('Нет ранее начатого заявления для проверки статуса.')
    app.transport_state='queued';app.transport_action='status';app.next_check_at=timezone.now();app.save();audit(app,'eta_status_requested',actor)
