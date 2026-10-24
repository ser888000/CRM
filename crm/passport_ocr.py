"""Local OCR only. Images are temporary; recognized fields are never saved here."""
import io
import os
import threading
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables

MAX_BYTES=6*1024*1024
OCR_LOCK=threading.BoundedSemaphore(1)


from .passport_parser import iso_date,mrz_digit,parse_passport
import time

class OCRLanguageError(Exception):pass

def recognize_image(image,kind,folder):
    from PIL import ImageOps,ImageFilter
    started=time.monotonic();texts=[];successful=[];best={}
    image.thumbnail((3000,3000))
    gray=ImageOps.autocontrast(ImageOps.grayscale(image)).filter(ImageFilter.SHARPEN)
    variants=[(gray,3,'rus+eng'),(gray,6,'eng'),(gray,11,'rus+eng')]
    lower=gray.crop((0,int(gray.height*.45),gray.width,gray.height))
    variants.extend([(lower,6,'eng'),(lower,11,'rus+eng')])
    # EXIF covers most phones; these passes also handle scans saved sideways/upside down.
    for rotation in (180,90,270):
        rotated=gray.rotate(rotation,expand=True)
        variants.extend([(rotated,6,'eng'),(rotated,11,'rus+eng')])
    for index,(variant,psm,lang) in enumerate(variants):
        remaining=42-(time.monotonic()-started)
        if remaining<2:break
        path=Path(folder)/f'page-{index}.png';variant.save(path)
        try:
            command=['tesseract',str(path),'stdout','-l',lang,'--psm',str(psm)]
            if lang=='eng':command+=['-c','tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<']
            process=subprocess.run(command,capture_output=True,text=True,timeout=min(8,remaining),check=True,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):continue
        if "Failed loading language 'rus'" in process.stderr:raise OCRLanguageError
        text=process.stdout[:20000];texts.append(text)
        fields=parse_passport(text,kind)
        if fields:successful.append((len(fields),text))
        # Keep complete name parts from the same pass, avoiding cross-pass mixed names.
        if fields.get('surname') and fields.get('given_name'):
            for key in ('surname','given_name','patronymic','name'):best.pop(key,None)
            best.update(fields)
        else:
            for key,value in fields.items():best.setdefault(key,value)
        if best.get('surname') and best.get('given_name') and best.get('passport_number') and best.get('birthday'):break
    return best,max(successful,key=lambda item:item[0])[1] if successful else max(texts,key=len,default='')


@login_required
@require_POST
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
def recognize(request):
    kind=request.POST.get('kind')
    model={'customer':'customer','tourist':'tourist'}.get(kind)
    if not model or not (request.user.has_perm('crm.add_'+model) or request.user.has_perm('crm.change_'+model)):
        return JsonResponse({'error':'Недостаточно прав для распознавания паспорта.'},status=403)
    upload=request.FILES.get('passport')
    if not upload or upload.size>MAX_BYTES:
        return JsonResponse({'error':'Выберите JPEG или PNG размером до 6 МБ.'},status=400)
    if not shutil.which('tesseract'):
        return JsonResponse({'error':'Распознавание ещё не установлено на сервере. Выполните deploy/install-ocr.sh.'},status=503)
    if not OCR_LOCK.acquire(blocking=False):
        return JsonResponse({'error':'Уже распознаётся другой паспорт. Повторите через минуту.'},status=429)
    try:
        from PIL import Image,ImageOps,UnidentifiedImageError
        Image.MAX_IMAGE_PIXELS=16_000_000
        with Image.open(io.BytesIO(upload.read())) as image:
            if image.format not in ('JPEG','PNG') or image.width*image.height>16_000_000:raise ValueError
            image=ImageOps.exif_transpose(image).convert('RGB')
            with tempfile.TemporaryDirectory(prefix='crm-passport-') as folder:
                fields,recognized_text=recognize_image(image,kind,folder)
        return JsonResponse({'fields':fields,'recognized_text':recognized_text,'message':'Проверьте распознанные поля перед сохранением. Незаполненные поля внесите вручную.' if fields else 'Не удалось выделить поля. Ниже доступен распознанный текст: проверьте, видит ли программа буквы и машиночитаемые строки. Можно загрузить отдельно страницу с данными.'})
    except OCRLanguageError:
        return JsonResponse({'error':'На сервере отсутствует русский язык Tesseract. Выполните deploy/install-ocr.sh.'},status=503)
    except ImportError:
        return JsonResponse({'error':'Обновите зависимости сервера через deploy/install-ocr.sh.'},status=503)
    except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning,UnidentifiedImageError):
        return JsonResponse({'error':'Не удалось прочитать изображение. Нужен JPEG/PNG до 16 мегапикселей.'},status=400)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
        return JsonResponse({'error':'Распознавание не завершилось. Попробуйте другое фото; проверьте установку языков rus и eng.'},status=503)
    finally:
        OCR_LOCK.release()
