import uuid
from datetime import timedelta
from django.db import transaction
from .models import Task, TaskTemplate, Contract

def task_due(contract,template):
    anchor={'created':contract.date,'start':contract.start,'end':contract.end}[template.anchor]
    if not anchor:
        return None
    # New tasks should not start overdue when the trip is booked at short notice.
    return max(contract.date,anchor+timedelta(days=template.offset))

def contract_task_schedule(contract,kind):
    template=kind.tasktemplate_set.order_by('order','pk').first()
    return {'due':task_due(contract,template) if template else contract.date,
            'anchor':template.anchor if template else 'created',
            'offset':template.offset if template else 0,'template':template}

@transaction.atomic
def create_contract_tasks(contract,kinds,dates):
    """Manual contract checklist, independent of Tourvisor's template selection."""
    for kind in kinds:
        if not kind.for_contract:continue
        if Task.objects.filter(contract=contract,task_type=kind).exists():continue
        schedule=contract_task_schedule(contract,kind);template=schedule['template']
        due=dates.get(kind.pk) or schedule['due']
        if not due:continue
        if template:
            create_tasks(contract,[template],{template.pk:due})
        else:
            Task.objects.get_or_create(origin_key=f'contract:{contract.pk}:type:{kind.pk}',defaults={
                'task_type':kind,'contract':contract,'customer':contract.customer,'title':kind.name,
                'description':kind.description,'due':due})

@transaction.atomic
def create_tasks(contract,templates=None,dates=None):
    if templates is None:
        templates=TaskTemplate.objects.filter(active=True)
    for template in templates:
        due=(dates or {}).get(template.pk) or task_due(contract,template)
        if due:
            Task.objects.get_or_create(origin_key=f'contract:{contract.pk}:template:{template.pk}',defaults={
                'task_type':template.task_type,'template':template,'contract':contract,'customer':contract.customer,'title':str(template),'due':due,
                'description':'\n'.join(v for v in ((template.task_type.description if template.task_type_id else ''),flight_description(contract) if template.copy_flights else '') if v)})

@transaction.atomic
def copy_contract(source):
    from django.utils import timezone
    copy = Contract.objects.get(pk=source.pk)
    copy.pk = None
    copy.exchange_id = uuid.uuid4()
    copy.number = ''
    copy.tourvisor_id = None
    copy.tourvisor_time = ''
    copy.imported_at = None
    copy.source_data = {}
    copy.date = timezone.localdate()
    copy.operator_paid = None
    copy.opening_operator_paid = 0
    copy.save()
    for line in source.lines.all():
        line.pk=None
        line.contract=copy
        line.save()
    return copy

@transaction.atomic
def repeat_tasks(task,period,count):
    import calendar
    from datetime import date
    if period not in ('day','week','month','year') or not 1 <= count <= 366:
        raise ValueError('Недопустимое правило повторения')
    copies=[]
    for i in range(1,count):
        if period in ('day','week'):
            due=task.due+timedelta(days=i*(7 if period=='week' else 1))
        else:
            months=task.due.year*12+task.due.month-1+i*(12 if period=='year' else 1)
            year,month=divmod(months,12);month+=1
            due=date(year,month,min(task.due.day,calendar.monthrange(year,month)[1]))
        copies.append(Task.objects.create(task_type=task.task_type,title=task.title,description=task.description,due=due,employee=task.employee,customer=task.customer,contract=task.contract,operator=task.operator,booking_number=task.booking_number))
    return copies


def flight_description(contract):
    lines=[]
    for flight in contract.source_data.get('transport',[]):
        lines.append(' · '.join(str(flight.get(k,'')) for k in ('number','datefrom','timefrom','terminalfrom','terminalto','dateto','timeto') if flight.get(k)))
    if contract.flights:lines.append(contract.flights)
    return '\n'.join(lines)
