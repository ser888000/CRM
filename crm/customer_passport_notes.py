"""Conservative extraction of a single customer's RF passport from legacy notes."""
import re
from datetime import date, datetime

DATE = r'\d{2}[./]\d{2}[./]\d{4}'
NUMBER = re.compile(r'\bпаспорт(?:\s+РФ)?\s*[:№]?\s*(\d{2}\s*\d{2})\s+(\d{6})(?!\d)', re.I)
RECORD = re.compile(
    rf'(?P<birth>{DATE})\s*г?\.?\s*р\.?\s*[,;]?\s*'
    r'паспорт(?:\s+РФ)?\s*[:№]?\s*(?P<series>\d{2}\s*\d{2})\s+(?P<number>\d{6})(?!\d)'
    rf'\s*[,;]?\s*выдан\s*[:]?\s*(?P<issued>{DATE})\s+'
    r'(?P<authority>[^\n]{5,500}?)\s*[,;]?\s*код\s+(?:подр\.?|подразделения)\s*[:.]?\s*'
    r'(?P<code>\d{3}\s*[-–—]\s*\d{3})(?!\d)', re.I)


def extract(notes):
    """Return fields or a review reason; never guess missing/ambiguous fragments."""
    if not re.search(r'паспорт', notes or '', re.I):
        return {}, ''
    matches = list(RECORD.finditer(notes))
    if len(matches) != 1 or len(NUMBER.findall(notes)) != 1:
        return {}, 'Формат не распознан или указано несколько паспортов'
    record = matches[0].groupdict()
    try:
        birthday = datetime.strptime(record['birth'].replace('/', '.'), '%d.%m.%Y').date()
        issued = datetime.strptime(record['issued'].replace('/', '.'), '%d.%m.%Y').date()
    except ValueError:
        return {}, 'Некорректная дата'
    if not date(1900, 1, 1) <= birthday < issued <= date.today():
        return {}, 'Проверьте даты рождения и выдачи'
    authority = ' '.join(record['authority'].strip(' ,;').split())
    if not re.search(r'МВД|ФМС|ОВД|УВД|ПОЛИЦ|ПАСПОРТ|МИЛИЦ', authority, re.I):
        return {}, 'Не распознано название органа выдачи'
    return dict(birthday=birthday, passport_number=re.sub(r'\s', '', record['series']) + record['number'],
                passport_issued=issued, passport_issued_by=authority,
                passport_code=re.sub(r'\s', '', record['code']).replace('–', '-').replace('—', '-')), ''


def plan(customer):
    fields, reason = extract(customer.passport)
    if not fields:
        return {}, reason
    if customer.kind != 'person' or customer.passport_type != '1':
        return {}, 'Карточка организации или заграничный паспорт'
    updates = {}
    for key, value in fields.items():
        current = getattr(customer, key)
        if not current:
            updates[key] = value
        elif key == 'passport_number':
            if re.sub(r'\D', '', current) != value:
                return {}, 'Паспорт в карточке отличается от примечания'
        elif key in ('passport_issued_by', 'passport_code'):
            if ' '.join(current.split()).casefold() != str(value).casefold():
                return {}, 'Данные в карточке отличаются от примечания'
        elif current != value:
            return {}, 'Даты в карточке отличаются от примечания'
    return updates, ''
