import json
from pathlib import Path
from django.db import migrations


def load_references(apps,schema_editor):
    source=Path(__file__).resolve().parent.parent/'data'/'locations_20261022.json'
    data=json.loads(source.read_text(encoding='utf-8'))
    for model_name,key in [('DepartureCity','cities'),('Country','countries')]:
        model=apps.get_model('crm',model_name)
        for record in data[key]:
            model.objects.using(schema_editor.connection.alias).get_or_create(code=record['code'],defaults={'name':record['name'],'details':record['details']})


class Migration(migrations.Migration):
    dependencies=[('crm','0004_country_departurecity')]
    operations=[migrations.RunPython(load_references,migrations.RunPython.noop)]
