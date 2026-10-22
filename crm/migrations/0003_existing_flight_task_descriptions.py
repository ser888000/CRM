from django.db import migrations


def fill_empty_descriptions(apps,schema_editor):
    Task=apps.get_model('crm','Task')
    tasks=Task.objects.using(schema_editor.connection.alias).filter(
        template__copy_flights=True,description='',contract__isnull=False,
    ).select_related('contract')
    for task in tasks.iterator():
        if task.contract.flights:
            task.description=task.contract.flights
            task.save(using=schema_editor.connection.alias,update_fields=['description'])


class Migration(migrations.Migration):
    dependencies=[('crm','0002_contracttype_paymentmethod_and_more')]
    operations=[migrations.RunPython(fill_empty_descriptions)]
