import sys,os,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ['DJANGO_SETTINGS_MODULE']='config.settings'
from django.conf import settings
from decimal import Decimal
with tempfile.TemporaryDirectory() as tmp:
 settings.DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':tmp+'/migration.sqlite3'}}
 import django
 django.setup()
 from django.db import connection
 from django.db.migrations.executor import MigrationExecutor
 ex=MigrationExecutor(connection);ex.migrate([('crm','0001_initial')])
 apps=ex.loader.project_state([('crm','0001_initial')]).apps
 customer=apps.get_model('crm','Customer').objects.create(name='Migration test')
 op=apps.get_model('crm','Operator').objects.create(name='Test TO')
 c=apps.get_model('crm','Contract').objects.create(customer=customer,operator=op,contract_type='Старый тип',payment_method='Перевод',flights='TEST 101')
 p=apps.get_model('crm','Payment').objects.create(contract=c,kind='customer',amount='100.00',method='Карта',rate='90.125000')
 template=apps.get_model('crm','TaskTemplate').objects.create(name='Проверить время вылета',anchor='start',offset=-1)
 task=apps.get_model('crm','Task').objects.create(title=template.name,template=template,contract=c,due='2026-11-01')
 custom=apps.get_model('crm','Task').objects.create(title=template.name,template=template,contract=c,due='2026-11-01',description='Не менять')
 ex=MigrationExecutor(connection);ex.migrate([('crm','0003_existing_flight_task_descriptions')])
 apps=ex.loader.project_state([('crm','0003_existing_flight_task_descriptions')]).apps
 c=apps.get_model('crm','Contract').objects.get(pk=c.pk)
 p=apps.get_model('crm','Payment').objects.get(pk=p.pk)
 assert c.contract_type.name=='Старый тип'
 assert c.payment_method.name=='Перевод'
 assert p.method.name=='Карта'
 assert p.amount==Decimal('100.00') and p.rate==Decimal('90.13')
 assert apps.get_model('crm','Task').objects.get(pk=task.pk).description=='TEST 101'
 assert apps.get_model('crm','Task').objects.get(pk=custom.pk).description=='Не менять'
 print('Existing contract, payment, dictionary values and rate rounding preserved by migration')
