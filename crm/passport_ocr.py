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


def iso_date(value):
    try:return datetime.strptime(value,'%d.%m.%Y').date().isoformat()
    except ValueError:return ''


def mrz_digit(value):
    chars='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return str(sum((0 if ch=='<' else chars.index(ch))*[7,3,1][i%3] for i,ch in enumerate(value))%10)


def parse_passport(text,kind):
    result={}
    # TD3 international passport: accept only fields with valid check digits.
    lines=[re.sub(r'\s','',line.upper()) for line in text.splitlines()]
    for index,line in enumerate(lines[:-1]):
        if not line.startswith('P<') or len(line)!=44:continue
        second=lines[index+1]
        if len(second)!=44 or not re.fullmatch(r'[A-Z0-9<]+',second):continue
        surname,_,given=line[5:].partition('<<')
        if kind=='tourist':
            result.update(surname=surname.replace('<',' ').strip(),given_name=given.replace('<',' ').strip())
            result['name']=' '.join([result['surname'],result['given_name']]).strip()
            if mrz_digit(second[:9])==second[9]:result['passport_number']=second[:9].replace('<','')
            for value,check,field in [(second[13:19],second[19],'birthday'),(second[21:27],second[27],'expires')]:
                if value.isdigit() and mrz_digit(value)==check:
                    year=int(value[:2]);year+=(1900 if field=='birthday' and year>datetime.now().year%100 else 2000)
                    try:result[field]=datetime(year,int(value[2:4]),int(value[4:6])).date().isoformat()
                    except ValueError:pass
            if second[20] in 'MF':result['gender']={'M':'male','F':'female'}[second[20]]
            result['passport_type']='0'
            result['nationality']=second[10:13].replace('<','')
        return result
    # Russian labelled fields. Do not guess names from unlabelled OCR lines.
    def field(label,pattern):
        match=re.search(label+r'\s*[:\-]?\s*('+pattern+r')',text,re.I)
        return match.group(1).strip() if match else ''
    for key,label in [('surname',r'ФАМИЛИЯ'),('given_name',r'(?<![А-Я])ИМЯ'),('patronymic',r'ОТЧЕСТВО')]:
        value=field(label,r'[А-ЯЁ][А-ЯЁа-яё\-]+')
        if value and (kind=='customer' or key!='patronymic'):result[key]=value.title()
    if result.get('surname') and result.get('given_name'):
        result['name']=' '.join(result.get(k,'') for k in ('surname','given_name','patronymic')).strip()
    birthday=field(r'ДАТА\s+РОЖДЕНИЯ',r'\d{2}\.\d{2}\.\d{4}')
    if birthday and iso_date(birthday):result['birthday']=iso_date(birthday)
    issued=field(r'ДАТА\s+ВЫДАЧИ',r'\d{2}\.\d{2}\.\d{4}')
    if issued and iso_date(issued):result['passport_issued' if kind=='customer' else 'issued']=iso_date(issued)
    code=re.search(r'\b\d{3}-\d{3}\b',text)
    if code and kind=='customer':result['passport_code']=code.group()
    number=re.search(r'(?<!\d)(\d{2})\s+(\d{2})\s+(\d{6})(?!\d)',text)
    if number:result['passport_number']=''.join(number.groups())
    issued_by=re.search(r'ПАСПОРТ\s+ВЫДАН\s+(.+?)(?=ДАТА\s+ВЫДАЧИ|\d{2}\.\d{2}\.\d{4}|КОД\s+ПОДРАЗДЕЛЕНИЯ)',text,re.I|re.S)
    if issued_by:
        value=' '.join(issued_by.group(1).split())
        if 4<len(value)<=250:result['passport_issued_by' if kind=='customer' else 'issued_by']=value
    return result


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
            image.thumbnail((2500,2500))
            with tempfile.TemporaryDirectory(prefix='crm-passport-') as folder:
                path=Path(folder)/'page.png';image.save(path)
                process=subprocess.run(['tesseract',str(path),'stdout','-l','rus+eng','--psm','3'],capture_output=True,text=True,timeout=35,check=True,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
        fields=parse_passport(process.stdout,kind)
        return JsonResponse({'fields':fields,'message':'Проверьте распознанные поля перед сохранением. Незаполненные поля внесите вручную.' if fields else 'Надёжно распознать поля не удалось. Попробуйте чёткое фото разворота паспорта без бликов или внесите данные вручную.'})
    except ImportError:
        return JsonResponse({'error':'Обновите зависимости сервера через deploy/install-ocr.sh.'},status=503)
    except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning,UnidentifiedImageError):
        return JsonResponse({'error':'Не удалось прочитать изображение. Нужен JPEG/PNG до 16 мегапикселей.'},status=400)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
        return JsonResponse({'error':'Распознавание не завершилось. Попробуйте другое фото; проверьте установку языков rus и eng.'},status=503)
    finally:
        OCR_LOCK.release()
