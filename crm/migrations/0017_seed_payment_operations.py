from django.db import migrations

def seed(apps,schema_editor):
    Operation=apps.get_model('crm','PaymentOperation')
    for code,name in [('customer','Поступление от клиента'),('customer_refund','Возврат клиенту'),('operator','Оплата ТО'),('operator_refund','Возврат от ТО')]:
        Operation.objects.get_or_create(code=code,defaults={'name':name})

class Migration(migrations.Migration):
    dependencies=[('crm','0016_paymentoperation')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
