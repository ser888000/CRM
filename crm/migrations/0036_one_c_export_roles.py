from django.db import migrations


def grant_roles(apps, schema_editor):
    alias = schema_editor.connection.alias
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    content_type, _ = ContentType.objects.using(alias).get_or_create(app_label='crm', model='contract')
    permissions = []
    for code, name in [('export_one_c', 'Выгрузка договоров в 1С'), ('view_contract', 'Can view Договор')]:
        permission, _ = Permission.objects.using(alias).get_or_create(
            content_type=content_type, codename=code, defaults={'name': name})
        permissions.append(permission)
    for name in ('Администратор', 'Бухгалтер'):
        group, _ = Group.objects.using(alias).get_or_create(name=name)
        group.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [('crm', '0035_one_c_export_permission')]
    operations = [migrations.RunPython(grant_roles, migrations.RunPython.noop)]
