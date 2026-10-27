import uuid
from django.db import migrations, models


def populate(apps, schema_editor):
    for name in ('Customer', 'Operator', 'Contract', 'Payment'):
        model = apps.get_model('crm', name)
        batch = []
        for obj in model.objects.using(schema_editor.connection.alias).all().iterator(chunk_size=500):
            obj.exchange_id = uuid.uuid4()
            batch.append(obj)
            if len(batch) == 500:
                model.objects.using(schema_editor.connection.alias).bulk_update(batch, ['exchange_id'])
                batch = []
        if batch:
            model.objects.using(schema_editor.connection.alias).bulk_update(batch, ['exchange_id'])


class Migration(migrations.Migration):
    dependencies = [('crm', '0033_task_result')]
    operations = [
        *[migrations.AddField(model_name=name, name='exchange_id', field=models.UUIDField(null=True, editable=False))
          for name in ('customer', 'operator', 'contract', 'payment')],
        migrations.RunPython(populate, migrations.RunPython.noop),
        *[migrations.AlterField(model_name=name, name='exchange_id', field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False))
          for name in ('customer', 'operator', 'contract', 'payment')],
    ]
