import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path
from django.test import SimpleTestCase

class CodePermissionTests(SimpleTestCase):
    def test_repairs_tracked_code_but_keeps_secrets_and_data_private(self):
        source=Path(__file__).resolve().parent.parent/'deploy/repair-code-permissions.py'
        spec=importlib.util.spec_from_file_location('code_permissions',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            repo=Path(folder)/'repo';repo.mkdir()
            subprocess.run(['git','init','-q',str(repo)],check=True)
            (repo/'.gitignore').write_text('.env\n.venv/\n*.sqlite3\n')
            package=repo/'crm';package.mkdir();(package/'forms.py').write_text('VALUE=1\n')
            script=repo/'install.sh';script.write_text('#!/bin/sh\n');script.chmod(0o755)
            subprocess.run(['git','add','.'],cwd=repo,check=True)
            (repo/'.env').write_text('PRIVATE=example');(repo/'.env').chmod(0o600)
            (repo/'db.sqlite3').write_text('private database');(repo/'db.sqlite3').chmod(0o600)
            (repo/'.venv').mkdir(mode=0o700)
            package.chmod(0o750);(package/'forms.py').chmod(0o640);script.chmod(0o750)
            self.assertFalse((package/'forms.py').stat().st_mode&0o004)
            module.repair(repo)
            self.assertEqual((package/'forms.py').stat().st_mode&0o777,0o644)
            self.assertEqual(package.stat().st_mode&0o777,0o755);self.assertEqual(script.stat().st_mode&0o777,0o755)
            for path in ('.env','db.sqlite3'):self.assertEqual((repo/path).stat().st_mode&0o777,0o600)
            self.assertEqual((repo/'.venv').stat().st_mode&0o777,0o700)
