from django.core.management.base import BaseCommand
from crm.models import TaskTemplate,TaskType
class Command(BaseCommand):
    help='Создать начальные шаблоны, не изменяя существующие'
    def handle(self,*args,**kwargs):
        for index,(name,anchor,offset) in enumerate([('Выслать подтверждение с номерами броней','created',0),('Выслать документы на вылет','start',-3),('Проверить время вылета','start',-1),('Связаться после поездки','end',2)],1):
            template,_=TaskTemplate.objects.get_or_create(name=name,defaults={'anchor':anchor,'offset':offset,'order':index*10,'copy_flights':name=='Проверить время вылета'})
            if not template.task_type_id:
                kind,_=TaskType.objects.get_or_create(name=name,defaults={'for_contract':True})
                template.task_type=kind;template.save(update_fields=['task_type'])
        self.stdout.write('Шаблоны готовы')
