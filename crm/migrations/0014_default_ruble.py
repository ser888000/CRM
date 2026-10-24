from django.db import migrations

def seed(apps,schema_editor):
    apps.get_model('crm','Currency').objects.filter(code='RUB').update(is_default=True)

class Migration(migrations.Migration):
    dependencies=[('crm','0013_contracttype_is_default_country_is_default_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
