import copy
from datetime import date,timedelta
from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth import get_user_model
from .models import Contract,Task,TaskTemplate,Payment,PaymentMethod,AuditEvent
from .tourvisor import apply_order,normalize_order,TourvisorError,GROUPS
from .tourvisor_diff import compare_order,task_moves
from .test_tourvisor import sample

class SyncTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser('owner','owner@example.test','test-password-123')
        self.client.force_login(self.user)
        self.order=sample()
        self.c=apply_order(self.order,self.user,set(GROUPS))
    def changed_trip(self):
        order=copy.deepcopy(self.order)
        order['flydate']='04.12.2026'
        order['transport'][0]['datefrom']='04.12.2026'
        order['transport'][1]['dateto']='11.12.2026'
        return order
    def task(self,anchor='start',done=False,due=date(2026,11,29)):
        template=TaskTemplate.objects.create(name='Задача '+anchor,anchor=anchor,offset=-1)
        return Task.objects.create(title=template.name,contract=self.c,template=template,due=due,done=done)
    def test_unchanged_order_has_no_preselected_changes(self):
        sections=compare_order(self.c,normalize_order(self.order))
        self.assertEqual([s['key'] for s in sections if s['changed']],[])
    def test_each_section_detects_actual_changes(self):
        variants={
            'customer':lambda o:o.update(phone='NEW'),
            'tour':lambda o:o.update(flydate='04.12.2026'),
            'tourists':lambda o:o['tourist'][0].update(passportenddate='01.01.2031'),
            'hotel':lambda o:o['hotel'][0].update(room='Новый номер'),
            'transport':lambda o:o['transport'][0].update(number='XX999'),
            'service':lambda o:o['service'][0].update(name='Новая услуга'),
            'amount':lambda o:o.update(price='210000')}
        for key,change in variants.items():
            with self.subTest(group=key):
                order=copy.deepcopy(self.order);change(order)
                sections=compare_order(self.c,normalize_order(order))
                self.assertEqual([s['key'] for s in sections if s['changed']],[key])
    def test_reordered_lists_and_service_dates_are_not_changes(self):
        order=copy.deepcopy(self.order)
        for key in ('tourist','transport','service'):order[key].reverse()
        order['service'][0]['startdate']='04.12.2026'
        self.assertFalse(any(s['changed'] for s in compare_order(self.c,normalize_order(order))))
    def test_task_candidates_preserve_custom_offsets_and_exclude_completed(self):
        t=self.task();after=self.task(anchor='end',due=date(2026,12,10))
        self.task(anchor='start',done=True);self.task(anchor='created')
        Task.objects.create(title='Ручная задача',contract=self.c,due=date(2026,12,1))
        moves=task_moves(self.c,normalize_order(self.changed_trip()))
        self.assertEqual({m['task'].pk for m in moves},{t.pk,after.pk})
        self.assertEqual([m['new'] for m in moves if m['task'].pk==t.pk],[date(2026,12,2)])
        self.assertEqual([m['new'] for m in moves if m['task'].pk==after.pk],[date(2026,12,13)])
    def test_preview_marks_changes_and_tasks_then_confirmation_moves_selected(self):
        t=self.task();not_selected=self.task(anchor='end',due=date(2026,12,10))
        with patch('crm.import_views.fetch_order',return_value=self.changed_trip()):
            r=self.client.post('/tourvisor/import/',{'action':'lookup','order_id':self.order['id']})
        self.assertEqual(r.status_code,200)
        self.assertEqual(set(r.context['confirm']['groups'].value()),{'tour','transport'})
        self.assertEqual(set(r.context['confirm']['move_tasks'].value()),{str(t.pk),str(not_selected.pk)})
        self.assertContains(r,'Сейчас в CRM')
        token=self.client.session['tourvisor_preview']['token']
        r=self.client.post('/tourvisor/import/',{'action':'confirm','token':token,'groups':['tour','transport'],'end':'2026-12-11','move_tasks':[t.pk],f'move_due_{t.pk}':'2026-12-02'})
        self.assertEqual(r.status_code,302)
        t.refresh_from_db();not_selected.refresh_from_db();self.c.refresh_from_db()
        self.assertEqual(t.due,date(2026,12,2));self.assertEqual(not_selected.due,date(2026,12,10))
        self.assertEqual(self.c.start,date(2026,12,4));self.assertEqual(self.c.end,date(2026,12,11))
        self.assertTrue(AuditEvent.objects.filter(object_type='crm.Task',object_id=str(t.pk),action='rescheduled').exists())
    def test_stale_or_completed_task_aborts_whole_update(self):
        t=self.task();old=t.due
        t.done=True;t.save()
        with self.assertRaises(TourvisorError):
            apply_order(self.changed_trip(),self.user,{'tour'},expected=self.c.pk,end=date(2026,12,11),task_updates=[{'id':t.pk,'old':str(old),'template':t.template_id,'new':date(2026,12,2)}])
        self.c.refresh_from_db();self.assertEqual(self.c.start,date(2026,12,1))
    def test_no_task_transfer_if_tour_section_is_unselected(self):
        t=self.task()
        with patch('crm.import_views.fetch_order',return_value=self.changed_trip()):
            self.client.post('/tourvisor/import/',{'action':'lookup','order_id':self.order['id']})
        token=self.client.session['tourvisor_preview']['token']
        r=self.client.post('/tourvisor/import/',{'action':'confirm','token':token,'groups':['transport'],'end':'2026-12-11','move_tasks':[t.pk],f'move_due_{t.pk}':'2026-12-02'})
        self.assertEqual(r.status_code,200);self.assertContains(r,'Для переноса задач выберите')
        self.c.refresh_from_db();self.assertEqual(self.c.start,date(2026,12,1))

    def test_selected_flight_task_refreshes_generated_text_and_preserves_suffix(self):
        from .services import flight_description
        t=self.task();t.template.copy_flights=True;t.template.save()
        t.description=flight_description(self.c)+'\nПроверить багаж';t.save()
        apply_order(self.changed_trip(),self.user,{'tour','transport'},expected=self.c.pk,end=date(2026,12,11),task_updates=[{'id':t.pk,'old':str(t.due),'template':t.template_id,'new':date(2026,12,2)}])
        t.refresh_from_db()
        self.assertIn('04.12.2026',t.description);self.assertTrue(t.description.endswith('Проверить багаж'))
    def test_no_selected_changes_is_a_noop(self):
        before=self.c.imported_at
        with patch('crm.import_views.fetch_order',return_value=self.order):
            self.client.post('/tourvisor/import/',{'action':'lookup','order_id':self.order['id']})
        token=self.client.session['tourvisor_preview']['token']
        r=self.client.post('/tourvisor/import/',{'action':'confirm','token':token,'end':'2026-12-08'})
        self.assertEqual(r.status_code,302)
        self.c.refresh_from_db();self.assertEqual(self.c.imported_at,before)

    def test_template_anchor_changed_after_preview_is_rejected(self):
        t=self.task()
        t.template.anchor='end';t.template.save()
        with self.assertRaises(TourvisorError):
            apply_order(self.changed_trip(),self.user,{'tour'},expected=self.c.pk,end=date(2026,12,11),task_updates=[{'id':t.pk,'old':str(t.due),'template':t.template_id,'anchor':'start','new':date(2026,12,2)}])
        self.c.refresh_from_db();self.assertEqual(self.c.start,date(2026,12,1))

    def test_hotel_changes_are_not_duplicated(self):
        changed=copy.deepcopy(self.order)
        changed['hotel'][0]['name']='Новое название'
        changed['hotel'][0]['room']='Новый номер'
        section=next(s for s in compare_order(self.c,normalize_order(changed)) if s['key']=='hotel')
        self.assertEqual(len(section['changes']),2)
        self.assertEqual([c['label'] for c in section['changes']],['Отель','Категория номера'])
    def test_money_scale_is_not_a_change(self):
        self.order['price']='200000.00'
        section=next(s for s in compare_order(self.c,normalize_order(self.order)) if s['key']=='amount')
        self.assertFalse(section['changed'])
    def test_service_rename_and_deletion_are_paired_by_name(self):
        from .tourvisor_diff import array_diff
        old=[{'name':'Медицинская страховка франшиза 30 у.е'},{'name':'Топливный сбор'},{'name':'Трансфер аэропорт - отель - аэропорт групповой'}]
        new=[{'name':'Медицинская страховка франшиза 30 у.е1111'},{'name':'Трансфер аэропорт - отель - аэропорт групповой1111'}]
        changes=array_diff(old,new,'service')
        self.assertEqual(len(changes),3)
        self.assertTrue(all(c['label']=='Название' for c in changes))
        self.assertIn({'label':'Название','old':'Топливный сбор','new':'—'},changes)
        self.assertIn({'label':'Название','old':old[2]['name'],'new':new[1]['name']},changes)
    def test_booking_prefix_and_explicit_template(self):
        operator=self.c.operator
        for template in ['https://agency.pegast.ru/MyAccount/Bookings/?bi=','https://agency.pegast.ru/MyAccount/Bookings/?bi={booking}']:
            operator.booking_url_template=template;operator.full_clean()
            self.assertEqual(operator.booking_link('12345'),'https://agency.pegast.ru/MyAccount/Bookings/?bi=12345')
