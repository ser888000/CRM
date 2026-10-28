from django.db import migrations, models


def transfer_status(apps, schema_editor):
    Contract=apps.get_model('crm','Contract')
    Contract.objects.using(schema_editor.connection.alias).filter(operator_paid__isnull=False).update(operator_paid_in_full=True)


class Migration(migrations.Migration):
    dependencies=[('crm','0037_alter_country_options_alter_currency_options_and_more')]
    operations=[
        migrations.AddField(model_name='contract',name='operator_paid_in_full',field=models.BooleanField(default=False,verbose_name='Оплачено ТО')),
        migrations.RunPython(transfer_status,migrations.RunPython.noop),
        migrations.RemoveField(model_name='contract',name='operator_paid'),
    ]
