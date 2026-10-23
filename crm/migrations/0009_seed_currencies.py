import json
from pathlib import Path
from django.db import migrations

def seed(apps,schema_editor):
    Currency=apps.get_model('crm','Currency')
    entries={'RUB':'Российский рубль','USD':'Доллар США','EUR':'Евро'}
    data=json.loads((Path(__file__).resolve().parent.parent/'data'/'locations_20261022.json').read_text())
    for country in data['countries']:
        d=country['details'];code=d.get('currency_code')
        if code and len(code)==3:entries.setdefault('RUB' if code=='RUR' else code,d.get('currency_name') or code)
    for code,name in entries.items():Currency.objects.using(schema_editor.connection.alias).get_or_create(code=code,defaults={'name':name})

class Migration(migrations.Migration):
    dependencies=[('crm','0008_currency')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
