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


def mrz_fields(text,kind):
    # OCR often prints spaces between MRZ characters or omits trailing fillers.
    lines=[re.sub(r'\s','',line.upper().replace('«','<<').replace('‹','<').replace('＜','<')) for line in text.splitlines()]
    lines=[line for line in lines if line]
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


def parse_passport(text,kind):
    result={};mrz=mrz_fields(text,kind)
    text=text.replace('\r','\n')
    # Printed labels may be bilingual and use punctuation or newlines.
    for key,label in [('surname',r'ФАМИЛИЯ'),('given_name',r'(?<![А-Я])ИМЯ'),('patronymic',r'ОТЧЕСТВО')]:
        pattern=label+r'(?:\s*[/|:]\s*(?:SURNAME|GIVEN\s+NAMES?|PATRONYMIC))?\s*[:.\-]?\s*([А-ЯЁ][А-ЯЁ\-]{1,50})\b'
        match=re.search(pattern,text,re.I)
        if match and match[1].upper() not in {'ИМЯ','ОТЧЕСТВО','ФАМИЛИЯ','ДАТА','РОССИЙСКАЯ','ПОЛ','РОЖДЕНИЯ'}:
            if kind=='customer' or key!='patronymic':result[key]=match[1].title()
    date_pattern=r'\d{2}\s*[. /-]\s*\d{2}\s*[. /-]\s*\d{4}'
    for label,key in [(r'ДАТА\s+РОЖДЕНИЯ','birthday'),(r'ДАТА\s+ВЫДАЧИ','passport_issued' if kind=='customer' else 'issued')]:
        match=re.search(label+r'(?:\s*[/|:]\s*DATE\s+OF\s+(?:BIRTH|ISSUE))?\s*[:.\-]?\s*('+date_pattern+')',text,re.I)
        if match and iso_date(match[1]):result[key]=iso_date(match[1])
    code=re.search(r'(?<!\d)\d{3}\s*[-–]\s*\d{3}(?!\d)',text)
    if code and kind=='customer':result['passport_code']=re.sub(r'\s','',code[0]).replace('–','-')
    number=re.search(r'(?<!\d)(\d{2})\s+(\d{2})\s+(\d{6})(?!\d)',text)
    if number:result['passport_number']=''.join(number.groups());result['passport_type']='1'
    issued_by=re.search(r'ПАСПОРТ\s+ВЫДАН\s+(.+?)(?=ДАТА\s+ВЫДАЧИ|'+date_pattern+r'|КОД\s+ПОДРАЗДЕЛЕНИЯ)',text,re.I|re.S)
    if issued_by:
        value=' '.join(issued_by[1].split())
        if 4<len(value)<=250:result['passport_issued_by' if kind=='customer' else 'issued_by']=value
    if mrz:
        # A customer's Russian printed name takes precedence over MRZ Latin names.
        if kind=='customer' and result.get('surname') and result.get('given_name'):
            mrz.pop('surname',None);mrz.pop('given_name',None);mrz.pop('name',None)
        result.update(mrz)
    if result.get('surname') and result.get('given_name'):
        result['name']=' '.join(result.get(k,'') for k in ('surname','given_name','patronymic') if result.get(k))
    return result
