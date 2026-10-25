import base64
import hashlib
import io
import json
import zipfile
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from .legacy_library import load_package,apply_package,LibraryImportError
from .models import LibraryEntry,LibraryAttachment,LegacyImportRun


def package(parent=-1,extra=False):
    raw=b'{\\rtf1\\ansi\\ansicpg1251 '+"Привет".encode('cp1251')+b'}'
    file=b'%PDF-test'
    manifest={'format':'aborigen-legacy-library-v1','source_key':'test','items':[{'id':1,'parent':parent,'title':'Раздел','original_b64':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}], 'files':[{'id':2,'entry_id':1,'name':'C:\\test.pdf','member':'files/2.bin','sha256':hashlib.sha256(file).hexdigest()}]}
    blob=io.BytesIO()
    with zipfile.ZipFile(blob,'w') as archive:
        archive.writestr('manifest.json',json.dumps(manifest));archive.writestr('files/2.bin',file)
        if extra:archive.writestr('../escape',b'bad')
    blob.seek(0)
    return blob


class LibraryTests(TestCase):
    def test_import_and_repeat_preserves_edits_and_originals(self):
        parsed=load_package(package());run,created=apply_package(parsed)
        self.assertTrue(created);entry=LibraryEntry.objects.get()
        self.assertEqual(entry.body,'Привет');self.assertEqual(entry.original_format,'rtf')
        self.assertEqual(bytes(entry.original_data),parsed['entries'][0]['original'])
        entry.body='Правка';entry.save()
        again,created=apply_package(load_package(package()))
        self.assertFalse(created);self.assertEqual(again.pk,run.pk)
        self.assertEqual(LibraryEntry.objects.get().body,'Правка')
        attachment=LibraryAttachment.objects.get()
        self.assertEqual(attachment.original_name,'test.pdf');self.assertEqual(bytes(attachment.data),b'%PDF-test')

    def test_missing_parent_kept_and_cycle_rejected(self):
        run,_=apply_package(load_package(package(999)))
        self.assertIsNone(LibraryEntry.objects.get().parent_id)
        self.assertEqual(run.issues[0]['kind'],'missing_parent')
        with self.assertRaises(LibraryImportError):load_package(package(1))

    def test_unsafe_and_corrupt_archives_rejected(self):
        for blob in [package(extra=True),io.BytesIO(b'broken')]:
            with self.assertRaises(LibraryImportError):load_package(blob)
        self.assertEqual(LegacyImportRun.objects.count(),0)

    def test_changed_snapshot_rejected_atomically(self):
        apply_package(load_package(package()))
        changed=load_package(package());changed['digest']='a'*64
        with self.assertRaises(LibraryImportError):apply_package(changed)
        self.assertEqual(LegacyImportRun.objects.count(),1)

    def test_permissions_search_and_safe_render(self):
        apply_package(load_package(package()))
        entry=LibraryEntry.objects.get();entry.body='<script>alert(1)</script>';entry.save()
        url=reverse('library_entry',args=[entry.pk])
        self.assertEqual(self.client.get(url).status_code,302)
        user=get_user_model().objects.create_user('reader')
        self.client.force_login(user);self.assertEqual(self.client.get(url).status_code,403)
        user.is_superuser=True;user.save()
        response=self.client.get(url)
        self.assertEqual(response.status_code,200);self.assertContains(response,'&lt;script&gt;');self.assertNotContains(response,'<script>alert')
        self.assertContains(self.client.get(reverse('library'),{'q':'РАЗДЕЛ'}),'Раздел')
        response=self.client.get(reverse('library_file',args=[LibraryAttachment.objects.get().pk]))
        self.assertEqual(b''.join(response.streaming_content),b'%PDF-test')
        self.assertIn('attachment',response['Content-Disposition'])
