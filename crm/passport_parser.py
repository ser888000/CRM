"""Parse OCR text conservatively; checksum-validated MRZ beats visual numbers."""
import re
from datetime import datetime,date


def iso_date(value):
    value=re.sub(r'\s*[./ -]\s*','.',value.strip())
    try:return datetime.strptime(value,'%d.%m.%Y').date().isoformat()
    except ValueError:return ''


def mrz_digit(value):
    chars='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return str(sum((0 if ch=='<' else chars.index(ch))*[7,3,1][i%3] for i,ch in enumerate(value))%10)


# GOST transliteration for the machine-readable zone of an internal RF passport.
RF_LETTERS=dict(zip('ABVGDE2JZIQKLMNOPRSTUFHC34WX Y9678'.replace(' ',''),
                    'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'))

def rf_mrz_fields(lines,kind):
    numeric=lambda value:value.translate(str.maketrans({'O':'0','I':'1','L':'1','B':'8'}))
    for index,first in enumerate(lines[:-1]):
        if not first.startswith('PNRUS'):continue
        names=first[5:].rstrip('<')
        if not re.fullmatch(r'[A-Z0-9<]+',names):continue
        surname,sep,rest=names.partition('<<');parts=[v for v in rest.split('<') if v]
        if not sep or not surname or not parts:continue
        second=lines[index+1]
        if len(second)!=44:continue
        birth=numeric(second[13:19]);birth_check=numeric(second[19])
        number=numeric(second[:9]);number_check=numeric(second[9])
        valid_birth=birth.isdigit() and mrz_digit(birth)==birth_check
        valid_number=number.isdigit() and mrz_digit(number)==number_check
        if not valid_birth and not valid_number:continue
        # Reject invalid name codes rather than guessing the person's spelling.
        def decode(value):
            return ''.join(RF_LETTERS[ch] for ch in value).title() if all(ch in RF_LETTERS for ch in value) else ''
        result={'passport_type':'1'}
        if decode(surname) and decode(parts[0]):
            result.update(surname=decode(surname),given_name=decode(parts[0]))
            if kind=='customer' and len(parts)>1 and decode(parts[1]):result['patronymic']=decode(parts[1])
        if valid_birth:
            year=int(birth[:2])+(1900 if int(birth[:2])>date.today().year%100 else 2000)
            try:result['birthday']=date(year,int(birth[2:4]),int(birth[4:6])).isoformat()
            except ValueError:pass
        # Additional data contains series digit 4, issue date and authority code.
        extra=numeric(second[28:41])+second[41]
        extra_check=numeric(second[42])
        if re.fullmatch(r'[0-9]{13}<',extra) and mrz_digit(extra)==extra_check:
            if valid_number:result['passport_number']=number[:3]+extra[0]+number[3:]
            issued=extra[1:7];year=int(issued[:2])+(1900 if int(issued[:2])>date.today().year%100 else 2000)
            try:result['passport_issued' if kind=='customer' else 'issued']=date(year,int(issued[2:4]),int(issued[4:6])).isoformat()
            except ValueError:pass
            if kind=='customer':result['passport_code']=extra[7:10]+'-'+extra[10:13]
        if kind=='tourist':
            gender=second[20].translate(str.maketrans({'М':'M','Ф':'F'}))
            if gender in 'MF':result['gender']={'M':'male','F':'female'}[gender]
            result['nationality']='Россия'
        return result
    return {}


def mrz_fields(text,kind):
    # OCR often prints spaces between MRZ characters or omits trailing fillers.
    lines=[re.sub(r'\s','',line.upper().replace('«','<<').replace('‹','<').replace('＜','<')) for line in text.splitlines()]
    lines=[line for line in lines if line]
    domestic=rf_mrz_fields(lines,kind)
    if domestic:return domestic
    for i,first in enumerate(lines[:-1]):
        if not re.fullmatch(r'P<[A-Z<]{3}[A-Z<]{20,}',first) or len(first)>44:continue
        second=lines[i+1]
        if not 28<=len(second)<=44 or not re.fullmatch(r'[A-Z0-9<]+',second):continue
        second=second.ljust(44,'<')
        # Repair O/I only in numeric date/check positions, then require checksums.
        numeric=lambda v:v.translate(str.maketrans({'O':'0','I':'1','L':'1','B':'8'}))
        checked=[]
        for value,check,key in [(second[13:19],second[19],'birthday'),(second[21:27],second[27],'expires')]:
            value=numeric(value);check=numeric(check)
            if value.isdigit() and mrz_digit(value)==check:
                year=int(value[:2])+(1900 if key=='birthday' and int(value[:2])>date.today().year%100 else 2000)
                try:checked.append((key,datetime(year,int(value[2:4]),int(value[4:6])).date().isoformat()))
                except ValueError:pass
        valid_number=mrz_digit(second[:9])==numeric(second[9])
        if not checked and not valid_number:continue
        surname,sep,given=first[5:].partition('<<')
        if not sep or not surname.strip('<') or not given.strip('<'):continue
        result={'surname':' '.join(surname.replace('<',' ').split()),'given_name':' '.join(given.replace('<',' ').split()),'passport_type':'0'}
        result['name']=result['surname']+' '+result['given_name']
        if valid_number:result['passport_number']=second[:9].replace('<','')
        for key,value in checked:
            if kind=='tourist' or key=='birthday':result[key]=value
        if kind=='tourist':
            if second[20] in 'MF':result['gender']={'M':'male','F':'female'}[second[20]]
            result['nationality']=second[10:13].replace('<','').translate(str.maketrans({'0':'O','1':'I','8':'B'}))
        return result
    return {}


def issuing_authority(text):
    """Read the authority block, tolerating OCR damage in printed labels only."""
    anchor=re.search(r'ПАСПОРТ\s+ВЫ[ДЛ]АН\b',text,re.I)
    if not anchor:return ''
    block=text[anchor.end():]
    boundary=re.search(
        r'(?:[ДЛА]АТА\s+[ВB][ЫИ][ДЛ]АЧ[ИЫ]|[КK][ОO][ДЛAА]\s+ПОДРАЗДЕЛЕНИЯ|'
        r'\d{2}\s*[.+/–—-]\s*\d{2}\s*[.+/–—-]\s*\d{4}|'
        r'ЛИЧНЫЙ\s+КОД|ЛИЧНАЯ\s+ПОДПИСЬ|ФАМИЛИЯ|PNRUS)',block,re.I)
    if boundary is None:return ''
    block=block[:boundary.start()]
    if len(block)>1500:return ''
    homographs=str.maketrans('ABCEHKMOPTXYabcehkmoptxy','АВСЕНКМОРТХУавсенкмортху')
    lines=[]
    for line in block.splitlines()[:16]:
        line=line.translate(homographs).strip(' _|=~;,:')
        cyrillic=len(re.findall(r'[А-ЯЁа-яё]',line));letters=len(re.findall(r'[^\W\d_]',line))
        # Drop isolated seal/watermark noise; never invent or expand an office name.
        if cyrillic>=5 and cyrillic>=letters*.75:lines.append(line)
    value=' '.join(' '.join(lines).split())
    if not re.search(r'ОТДЕЛ|УФМС|УМВД|МВД|ГУВД|ОВД|ФМС|УПРАВЛ|ПОЛИЦ|МИД|УВД',value,re.I):return ''
    return value if 5<=len(value)<=500 else ''


def parse_passport(text,kind,include_mrz=True):
    result={};mrz=mrz_fields(text,kind) if include_mrz else {}
    text=text.replace('\r','\n')
    # Printed labels may be bilingual and use punctuation or newlines.
    for key,label in [('surname',r'ФАМИЛИЯ'),('given_name',r'(?<![А-Я])ИМЯ'),('patronymic',r'ОТЧЕСТВО')]:
        pattern=label+r'(?:\s*[/|:]\s*(?:SURNAME|GIVEN\s+NAMES?|PATRONYMIC))?\s*[:.\-]?\s*([А-ЯЁ][А-ЯЁ\-]{1,50})\b'
        match=re.search(pattern,text,re.I)
        if not match:
            match=re.search(r'(?:^|\n)\s*([А-ЯЁ][А-ЯЁ\-]{1,49})\s*\n\s*'+label+r'\b',text,re.I)
        if match and match[1].upper() not in {'ИМЯ','ОТЧЕСТВО','ФАМИЛИЯ','ДАТА','РОССИЙСКАЯ','ПОЛ','РОЖДЕНИЯ'}:
            if kind=='customer' or key!='patronymic':result[key]=match[1].title()
    date_pattern=r'\d{2}\s*[. /-]\s*\d{2}\s*[. /-]\s*\d{4}'
    for label,key in [(r'ДАТА\s+РОЖДЕНИЯ','birthday'),(r'ДАТА\s+ВЫДАЧИ','passport_issued' if kind=='customer' else 'issued')]:
        match=re.search(label+r'(?:\s*[/|:]\s*DATE\s+OF\s+(?:BIRTH|ISSUE))?\s*[:.\-]?\s*('+date_pattern+')',text,re.I)
        if match and iso_date(match[1]):result[key]=iso_date(match[1])
    code=re.search(r'(?<!\d)\d{3}\s*[-–—]\s*\d{3}(?!\d)',text)
    if code and kind=='customer':result['passport_code']=re.sub(r'\s','',code[0]).replace('–','-').replace('—','-')
    number=re.search(r'(?<!\d)(\d{2})\s+(\d{2})\s+(\d{6})(?!\d)',text)
    if number:result['passport_number']=''.join(number.groups());result['passport_type']='1'
    issuer=issuing_authority(text)
    if issuer and len(issuer)<=(500 if kind=='customer' else 250):result['passport_issued_by' if kind=='customer' else 'issued_by']=issuer
    if mrz:
        if mrz.get('passport_type')=='1':
            # RF layouts may print labels below the values. Prefer clearly read
            # Cyrillic name parts to a damaged transliteration in the MRZ.
            for key in ('surname','given_name','patronymic'):
                if result.get(key):mrz[key]=result[key]
        # A customer's Russian printed name takes precedence over MRZ Latin names.
        if kind=='customer' and mrz.get('passport_type')!='1' and result.get('surname') and result.get('given_name'):
            mrz.pop('surname',None);mrz.pop('given_name',None);mrz.pop('name',None)
        result.update(mrz)
    if result.get('surname') and result.get('given_name'):
        result['name']=' '.join(result.get(k,'') for k in ('surname','given_name','patronymic') if result.get(k))
    return result
