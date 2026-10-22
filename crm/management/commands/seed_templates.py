from django.core.management.base import BaseCommand
from crm.models import TaskTemplate
class Command(BaseCommand):
    help='Создать начальные шаблоны, не изменяя существующие'
    def handle(self,*args,**kwargs):
        for name,anchor,offset in [('Выслать подтверждение с номерами броней','created',0),('Выслать документы на вылет','start',-3),('Проверить время вылета','start',-1),('Связаться после поездки','end',2)]:
            TaskTemplate.objects.get_or_create(name=name,defaults={'anchor':anchor,'offset':offset})
        self.stdout.write('Шаблоны готовы')
