from django.db import migrations


def seed(apps,schema_editor):
    Contract=apps.get_model('crm','Contract')
    for model,field,defaults in [
        ('Meal','meal',['RO — Без питания','BB — Завтраки','HB — Полупансион','FB — Полный пансион','AI — Всё включено','UAI — Ультра всё включено']),
        ('Transfer','transfer',['Групповой','Индивидуальный','Не включён']),
        ('Insurance','insurance',['Медицинская','От невыезда','Не включена']),
        ('FuelSurcharge','fuel_surcharge',['Включён в стоимость','Без топливного сбора']),
    ]:
        Reference=apps.get_model('crm',model)
        values=set(defaults)|set(Contract.objects.exclude(**{field:''}).values_list(field,flat=True))
        for value in values:
            if value and len(value)<=100:Reference.objects.get_or_create(name=value)


class Migration(migrations.Migration):
    dependencies=[('crm','0011_fuelsurcharge_insurance_meal_transfer_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
