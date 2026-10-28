"""Explicit, atomic replacement of training business data, preserving approved sections."""
from django.db import transaction
from . import models as m
from .legacy_history import prepare_history,apply_history,HistoryImportError

@transaction.atomic
def clear_history(actor=None,progress=lambda message:None):
    progress('Очищаем данные; библиотека и сохранённые справочники остаются')
    templates=[]
    for t in m.TaskTemplate.objects.select_related('task_type'):
        if t.task_type_id:
            kind=t.task_type
            templates.append((t.pk,{'name':kind.name,'description':kind.description,'for_contract':kind.for_contract,'sort_order':kind.sort_order,'is_default':kind.is_default}))
    counts={}
    for model in (m.TourvisorBatch,m.Task,m.Payment,m.Booking,m.ContractLine,m.Contract,m.Tourist,m.Customer,m.Operator,m.PaymentMethod,m.ContractType,m.Meal,m.Transfer,m.Insurance,m.FuelSurcharge,m.TaskType):
        counts[model._meta.label]=model.objects.count();model.objects.all().delete()
    # Library journal/entries/files and authentication users remain untouched.
    runs=m.LegacyImportRun.objects.filter(section='history')
    m.LegacyRecord.objects.filter(import_run__in=runs).delete();runs.delete()
    for pk,values in templates:
        kind,_=m.TaskType.objects.get_or_create(name=values.pop('name'),defaults=values)
        m.TaskTemplate.objects.filter(pk=pk).update(task_type=kind)
    from django.contrib.sessions.models import Session
    from django.contrib.sessions.backends.db import SessionStore
    from django.utils import timezone
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        values=session.get_decoded()
        if any(key in values for key in ('contract_journal','finance_journal','task_journal','customer_journal')):
            for key in ('contract_journal','finance_journal','task_journal','customer_journal'):values.pop(key,None)
            session.session_data=SessionStore().encode(values);session.save(update_fields=['session_data'])
    m.AuditEvent.objects.create(actor=actor,object_type='crm.LegacyImportRun',object_id='',action='training_history_cleared',changes={'cleared_counts':counts})
    return counts


@transaction.atomic
def replace_history(data,actor=None,progress=lambda message:None):
    if data.get('format')!='aborigen-legacy-history-v2':raise HistoryImportError('Для новой загрузки выберите новый пакет истории (версия 2).')
    prepare_history(data)
    counts=clear_history(actor,progress)
    run,created=apply_history(data,actor,progress)
    run.summary={**run.summary,'replaced_training':True,'cleared_counts':counts};run.save(update_fields=['summary'])
    m.AuditEvent.objects.create(actor=actor,object_type='crm.LegacyImportRun',object_id=str(run.pk),action='training_history_replaced',changes={'cleared_counts':counts})
    return run,created
