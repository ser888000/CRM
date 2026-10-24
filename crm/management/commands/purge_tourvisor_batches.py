from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from crm.models import TourvisorBatch,TourvisorBatchRow

class Command(BaseCommand):
    help='Clear expired Tourvisor preview snapshots and remove batch metadata after seven days.'
    def handle(self,*args,**options):
        now=timezone.now()
        rows=TourvisorBatchRow.objects.filter(batch__expires_at__lte=now).exclude(payload={}).update(payload={},plan={})
        deleted,_=TourvisorBatch.objects.filter(created_at__lt=now-timedelta(days=7)).delete()
        self.stdout.write(f'Expired snapshots cleared: {rows}; old records removed: {deleted}')
