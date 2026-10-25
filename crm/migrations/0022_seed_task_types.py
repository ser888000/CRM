from django.db import migrations


def seed(apps,schema_editor):
    Task=apps.get_model('crm','Task');Template=apps.get_model('crm','TaskTemplate');Type=apps.get_model('crm','TaskType')
    alias=schema_editor.connection.alias
    names=set(Task.objects.using(alias).values_list('title',flat=True))|set(Template.objects.using(alias).values_list('name',flat=True))
    for name in sorted(names):
        if not name:continue
        kind,_=Type.objects.using(alias).get_or_create(name=name)
        Task.objects.using(alias).filter(title=name,task_type__isnull=True).update(task_type=kind)
        Template.objects.using(alias).filter(name=name,task_type__isnull=True).update(task_type=kind)

class Migration(migrations.Migration):
    dependencies=[('crm','0021_tasktemplate_task_type')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
