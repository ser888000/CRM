import json
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from crm.legacy_history import load_history,prepare_history,apply_history,HistoryImportError

class Command(BaseCommand):
    help='Проверка и атомарная тренировочная загрузка истории старой CRM'
    def add_arguments(self,parser):
        parser.add_argument('package',nargs='?')
        parser.add_argument('--dry-run',action='store_true')
        parser.add_argument('--actor',type=int)
        parser.add_argument('--job')
    def handle(self,*args,**options):
        if options['job']:
            from crm.legacy_history_jobs import run_job
            run_job(options['job']);return
        if not options['package']:raise CommandError('Укажите ZIP истории.')
        try:
            with open(options['package'],'rb') as file:data=load_history(file)
            if options['dry_run']:
                _,_,report=prepare_history(data)
                self.stdout.write(json.dumps(report,ensure_ascii=False));return
            actor=get_user_model().objects.get(pk=options['actor']) if options['actor'] else None
            run,created=apply_history(data,actor)
            self.stdout.write(json.dumps({'created':created,**run.summary},ensure_ascii=False))
        except (OSError,HistoryImportError,get_user_model().DoesNotExist) as error:raise CommandError(str(error))
