import subprocess
import sys
from django.conf import settings
from django.test import SimpleTestCase

class UpgradeTests(SimpleTestCase):
    def test_existing_data_survives_reference_conversion(self):
        result=subprocess.run([sys.executable,str(settings.BASE_DIR/'scripts/check_migration.py')],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
