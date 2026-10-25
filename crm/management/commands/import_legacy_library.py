from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from crm.legacy_library import load_package,apply_package,LibraryImportError

class Command(BaseCommand):
    help='Проверить или загрузить подготовленный пакет старой библиотеки'
    def add_arguments(self,parser):
        parser.add_argument('package')
        parser.add_argument('--dry-run',action='store_true')
        parser.add_argument('--actor',type=int)
    def handle(self,*args,**options):
        try:
            with open(options['package'],'rb') as source:package=load_package(source)
            if options['dry_run']:
                self.stdout.write(f"Validated: {len(package['entries'])} entries, {len(package['files'])} files; no database changes")
                return
            actor=get_user_model().objects.get(pk=options['actor']) if options['actor'] else None
            run,created=apply_package(package,actor)
        except (OSError,LibraryImportError,get_user_model().DoesNotExist) as error:raise CommandError(str(error))
        self.stdout.write(f"{'Imported' if created else 'Already imported'}: {run.summary['entries']} entries, {run.summary['files']} files, {run.summary['issues']} issues")
