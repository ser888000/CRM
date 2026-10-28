from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied,FieldDoesNotExist
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404,redirect,render
from django.http import Http404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from django.forms.models import model_to_dict
from django import forms
from .models import Contract,Payment,Booking,ContractLine,Task,Tourist,AuditEvent,LegacyRecord
from .card_forms import CardContractForm,CustomerCardForm,TouristCardForm,CardPaymentForm,BookingCardForm,LineCardForm,TaskCardForm
from .services import create_tasks,create_contract_tasks,copy_contract

GROUPS=[('Основное',['number','date','contract_type','customer','operator','payment_method','notes']),('Тур',['country','region','departure','start','end','nights','tour_name','hotel','room','meal','adults','children','infants','source_currency']),('Услуги и перелёты',['flights','transfer','insurance','fuel_surcharge','services']),('Дополнительно',['metrika_id'])]

def require(user,*perms):
    if not user.has_perms(perms):raise PermissionDenied

def audit(user,obj,before,action):
    after=model_to_dict(obj)
    changes={k:{'old':str(before.get(k)),'new':str(v)} for k,v in after.items() if before.get(k)!=v}
    AuditEvent.objects.create(actor=user,object_type=obj._meta.label,object_id=str(obj.pk),action=action,changes=changes)

@login_required
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
@transaction.atomic
def contract_card(request,pk=None):
    require(request.user,'crm.view_contract' if pk else 'crm.add_contract')
    contract=get_object_or_404(Contract.objects.select_related('customer','operator').select_for_update(),pk=pk) if pk else Contract()
    action=(request.POST.get('delete_action') or request.POST.get('action')) if request.method=='POST' else ''
    form=CardContractForm(request.POST if action=='contract' else None,instance=contract)
    customer_form=CustomerCardForm(request.POST if action=='customer' else None,instance=contract.customer if pk else None,prefix='customer')
    payment_form=CardPaymentForm(prefix='payment-new')
    booking_form=BookingCardForm(prefix='booking-new')
    line_form=LineCardForm(prefix='line-new')
    task_form=TaskCardForm(prefix='task-new')
    tourist_form=TouristCardForm(prefix='tourist-new')
    deadline=forms.Form(request.POST if action=='operator_due' else None,initial={'due':contract.operator_due})
    deadline.fields['due']=forms.DateField(label='Срок оплаты ТО (общий для всех броней)',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    active=request.GET.get('tab','overview')
    invalid_form=None;invalid_id=None;invalid_action=None
    if action=='contract':
        require(request.user,'crm.change_contract' if pk else 'crm.add_contract')
        if form.is_valid():
            selected=form.cleaned_data.get('task_templates',[])
            if selected:require(request.user,'crm.add_task')
            if pk and form.cleaned_data['version']!=str(contract.updated_at):
                form.add_error(None,'Договор изменился в другом окне. Обновите страницу перед сохранением.')
            else:
                before=model_to_dict(Contract.objects.get(pk=pk)) if pk else {}
                saved=form.save()
                create_contract_tasks(saved,selected,{t.pk:form.cleaned_data[f'task_due_{t.pk}'] for t in selected})
                audit(request.user,saved,before,'card_saved')
                messages.success(request,'Договор сохранён.')
                return redirect('contract_card',pk=saved.pk)
    elif action:
        if not pk:raise PermissionDenied
        if action=='operator_due':
            require(request.user,'crm.change_contract')
            active='bookings'
            if deadline.is_valid():
                if request.POST.get('version')!=str(contract.updated_at):
                    deadline.add_error(None,'Договор изменился. Обновите страницу перед сохранением.')
                else:
                    before=model_to_dict(contract);contract.operator_due=deadline.cleaned_data['due']
                    contract.save(update_fields=['operator_due','updated_at']);audit(request.user,contract,before,'operator_due_updated')
                    return redirect('/contracts/'+str(pk)+'/?tab=bookings')
        elif action=='copy':
            require(request.user,'crm.add_contract','crm.add_contractline')
            cloned=copy_contract(contract);audit(request.user,cloned,{},'copied')
            messages.success(request,'Создана копия без оплат, броней, задач и связи с Турвизором. Проверьте даты и номер.')
            return redirect('contract_card',pk=cloned.pk)
        elif action in ('delete_tourist','delete_line'):
            require(request.user,'crm.change_contractline' if action=='delete_tourist' else 'crm.delete_contractline')
            line_id=request.POST.get('line_id') or request.POST.get('entry_id','')
            if not line_id.isdecimal() or len(line_id)>18:raise Http404
            line=get_object_or_404(ContractLine,pk=line_id,contract=contract)
            before=model_to_dict(line)
            if action=='delete_tourist':
                if str(line.tourist_id)!=request.POST.get('entry_id'):raise Http404
                line.tourist=None;line.tourist_snapshot={};line.save(update_fields=['tourist','tourist_snapshot'])
                audit(request.user,line,before,'tourist_detached')
                messages.success(request,'Турист убран из строки договора. Строка стоимости и карточка туриста в справочнике сохранены.')
            else:
                AuditEvent.objects.create(actor=request.user,object_type='crm.Contract',object_id=str(contract.pk),action='line_deleted',changes={'line':{'old':str(line.pk),'new':None},'amount':{'old':str(line.amount),'new':None},'tourist':{'old':str(line.tourist_id),'new':None}})
                line.delete();messages.success(request,'Строка стоимости удалена.')
            contract.save(update_fields=['updated_at'])
            return redirect('/contracts/'+str(pk)+'/?tab=tourists')
        elif action=='customer':
            require(request.user,'crm.change_customer');active='customer'
            if customer_form.is_valid():
                before=model_to_dict(type(contract.customer).objects.get(pk=contract.customer_id))
                saved=customer_form.save();audit(request.user,saved,before,'card_customer_saved')
                messages.success(request,'Заказчик сохранён. Изменения действуют во всех его договорах.')
                return redirect('/contracts/'+str(pk)+'/?tab=customer')
        elif action in ('payment','booking','line','task'):
            specs={'payment':(Payment,CardPaymentForm),'booking':(Booking,BookingCardForm),'line':(ContractLine,LineCardForm),'task':(Task,TaskCardForm)}
            model,formclass=specs[action]
            entry_id=request.POST.get('entry_id')
            if entry_id and (not entry_id.isdecimal() or len(entry_id)>18):raise Http404
            if entry_id and action=='task':entry=get_object_or_404(Task.objects.filter(Q(contract=contract)|Q(contract__isnull=True,customer=contract.customer)),pk=entry_id)
            else:entry=get_object_or_404(model,pk=entry_id,contract=contract) if entry_id else model(contract=contract)
            require(request.user,f'crm.{"change" if entry_id else "add"}_{model._meta.model_name}')
            before=model_to_dict(entry) if entry_id else {}
            subform=formclass(request.POST,instance=entry,prefix=action+'-'+(entry_id or 'new'))
            active={'payment':'finance','booking':'bookings','line':'tourists','task':'tasks'}[action]
            if subform.is_valid():
                saved=subform.save(commit=False)
                if action!='task' or not entry_id:saved.contract=contract
                if action=='task':saved.customer=contract.customer
                saved.save();audit(request.user,saved,before,'card_'+action+'_saved')
                contract.save(update_fields=['updated_at'])
                messages.success(request,'Изменения сохранены.')
                return redirect('/contracts/'+str(pk)+'/?tab='+active)
            invalid_form=subform;invalid_id=entry_id;invalid_action=action
            if action=='payment' and not entry_id:payment_form=subform
            elif action=='booking' and not entry_id:booking_form=subform
            elif action=='line' and not entry_id:line_form=subform
            elif not entry_id:task_form=subform
        elif action=='tourist':
            require(request.user,'crm.change_tourist' if request.POST.get('entry_id') else 'crm.add_tourist')
            active='tourists'
            entry_id=request.POST.get('entry_id')
            if entry_id and (not entry_id.isdecimal() or len(entry_id)>18):raise Http404
            if not entry_id:require(request.user,'crm.add_contractline')
            tourist=get_object_or_404(Tourist.objects.filter(contractline__contract=contract).distinct(),pk=entry_id) if entry_id else Tourist()
            before=model_to_dict(tourist) if entry_id else {}
            tourist_form=TouristCardForm(request.POST,instance=tourist,prefix='tourist-'+(entry_id or 'new'))
            invalid_form=tourist_form;invalid_id=entry_id;invalid_action='tourist'
            if tourist_form.is_valid():
                tourist=tourist_form.save()
                if not entry_id:ContractLine.objects.create(contract=contract,tourist=tourist,description=tourist.name,amount=0)
                audit(request.user,tourist,before,'card_tourist_saved')
                contract.save(update_fields=['updated_at'])
                messages.success(request,'Турист сохранён.')
                return redirect('/contracts/'+str(pk)+'/?tab=tourists')
        else:raise PermissionDenied
    if pk:
        payments=list(contract.payments.select_related('method','legacy_payer').order_by('-date','-pk')) if request.user.has_perm('crm.view_payment') else []
        for p in payments:p.edit_form=invalid_form if invalid_action=='payment' and invalid_id==str(p.pk) else CardPaymentForm(instance=p,prefix=f'payment-{p.pk}')
        task_query=Task.objects.filter(Q(contract=contract)|Q(contract__isnull=True,customer=contract.customer)).select_related('employee','task_type').order_by('done','-due','pk')
        task_count=task_query.count() if request.user.has_perm('crm.view_task') else 0
        tasks=list(task_query[:100]) if request.user.has_perm('crm.view_task') else []
        for t in tasks:t.edit_form=invalid_form if invalid_action=='task' and invalid_id==str(t.pk) else TaskCardForm(instance=t,prefix=f'task-{t.pk}')
        lines=list(contract.lines.select_related('tourist'))
        for line in lines:
            line.edit_form=invalid_form if invalid_action=='line' and invalid_id==str(line.pk) else LineCardForm(instance=line,prefix=f'line-{line.pk}')
            if line.tourist:line.tourist_form=invalid_form if invalid_action=='tourist' and invalid_id==str(line.tourist_id) else TouristCardForm(instance=line.tourist,prefix=f'tourist-{line.tourist_id}')
        bookings=list(contract.bookings.all())
        for b in bookings:b.edit_form=invalid_form if invalid_action=='booking' and invalid_id==str(b.pk) else BookingCardForm(instance=b,prefix=f'booking-{b.pk}')
        ids={'crm.Payment':[str(p.pk) for p in payments],'crm.Task':[str(t.pk) for t in tasks],'crm.ContractLine':[str(l.pk) for l in lines],'crm.Booking':[str(b.pk) for b in bookings],'crm.Customer':[str(contract.customer_id)],'crm.Tourist':[str(l.tourist_id) for l in lines if l.tourist_id]}
        query=Q(object_type='crm.Contract',object_id=str(pk))
        for kind,values in ids.items():query|=Q(object_type=kind,object_id__in=values)
        history=list(AuditEvent.objects.filter(query).select_related('actor')[:60]) if request.user.has_perm('crm.view_auditevent') else []
        from django.apps import apps
        from .templatetags.money import money
        labels={'line_deleted':'Строка стоимости удалена','tourist_detached':'Турист убран из строки договора','card_saved':'Договор сохранён','card_customer_saved':'Данные заказчика изменены','card_payment_saved':'Финансовая операция сохранена','card_booking_saved':'Бронь ТО сохранена','card_line_saved':'Стоимость изменена','card_task_saved':'Задача сохранена','card_tourist_saved':'Данные туриста изменены','tourvisor_created':'Договор импортирован из Турвизора','tourvisor_updated':'Данные обновлены из Турвизора','created':'Запись создана','updated':'Запись изменена','inline_saved':'Строка договора сохранена','completed':'Задача выполнена','reopened':'Задача возвращена в запланированные','rescheduled':'Задача перенесена','copied':'Договор скопирован'}
        for event in history:
            event.display_action=labels.get(event.action,'Изменение записи')
            event.details=[]
            try:model=apps.get_model(event.object_type)
            except (LookupError,ValueError):model=None
            for field,change in event.changes.items():
                if isinstance(change,dict) and 'old' in change and 'new' in change:
                    try:label=model._meta.get_field(field).verbose_name if model else field
                    except (FieldDoesNotExist,AttributeError):label=field
                    old,new=change['old'],change['new']
                    if field in ('amount','rate'):old,new=money(old),money(new)
                    event.details.append((label,old,new))

    else:payments=[];tasks=[];lines=[];bookings=[];history=[];task_count=0
    legacy_record=LegacyRecord.objects.filter(target_model='crm.Contract',target_id=pk).only('pk','source_id','payload').first() if pk else None
    snapshot_fields=[]
    if pk and request.user.has_perm('crm.view_customer'):
        labels={'FIO_REQUIS_FIZ':'ФИО','FULL_NAME':'Организация','PASPORT_NUMBER':'Паспорт','PASPORT_VIDAN_DATA':'Дата выдачи','PASPORT_VIDAN_KEM':'Кем выдан','KOD_PODRAZDELEN_FIZ':'Код подразделения','ADDRES_PROPIS':'Адрес регистрации','ADRES_YUR':'Юридический адрес','INN':'ИНН','KPP':'КПП','RS':'Расчётный счёт','BANK_NAME':'Банк','KONT_TEL':'Телефон','EMAIL_FIZ':'Email'}
        for values in contract.legacy_customer_snapshot.values():
            snapshot_fields.extend((label,str(values[key])) for key,label in labels.items() if values.get(key))
    return render(request,'crm/contract_card.html',{'legacy_operator_original':legacy_record.payload.get('ADD_SUM_OPLATY_TO',0) if legacy_record else 0,'legacy_record':legacy_record,'legacy_snapshot_fields':snapshot_fields,'contract':contract,'is_new':not pk,'form':form,'operator_due_form':deadline,'field_groups':[(title,[form[name] for name in fields]) for title,fields in GROUPS],
        'schedule_fields':[f for f in form if f.name.startswith('task_due_')], 'contract_task_rows':[{'kind':kind,'selected':str(kind.pk) in {str(v) for v in (form['task_templates'].value() or [])},'date':form[f'task_due_{kind.pk}']} for kind in form.fields['task_templates'].queryset], 'new_customer_form':CustomerCardForm(prefix='customer-new'),'customer_form':customer_form,'payment_form':payment_form,'booking_form':booking_form,'line_form':line_form,'task_form':task_form,'tourist_form':TouristCardForm(prefix='tourist-new') if invalid_action=='tourist' and invalid_id else tourist_form,
        'payment_groups':[('Заказчик',[p for p in payments if p.kind in ('customer','customer_refund')]),('Туроператор',[p for p in payments if p.kind in ('operator','operator_refund')])],'payments':payments,'task_count':task_count,'has_more_tasks':task_count>len(tasks),'tasks':tasks,'lines':lines,'bookings':bookings,'history':history,'active_tab':active})
