"""Conservative extraction of a single customer's RF passport from legacy notes."""
import re
from datetime import date, datetime

DATE = r'\d{2}[./]\d{2}[./]\d{4}'
# Exactly ten digits; spaces may split either the series or the number.
DIGITS = r'(?<!\d)\d(?:[ \t]*\d){9}(?![ \t]*\d)'
NUMBER = re.compile(DIGITS)
RECORD = re.compile(
    rf'(?<!\d)(?P<birth>{DATE})\s*(?:г?\.?\s*р\.?)?\s*[,;]?\s*'
    rf'(?:паспорт(?:\s+РФ)?\s*[:№]?\s*)?(?P<number>{DIGITS})', re.I)
CODE = re.compile(
    r'(?:[,;]?\s*(?:код\s+(?:подр\.?|подразделения)\s*[:.]?\s*)?)'
    r'(?<!\d)(?P<code>\d{3}\s*[-–—]?\s*\d{3})(?!\d)\s*[.;]?\s*$', re.I)
LABELED_CODE = re.compile(r'[,;]?\s*код\s+(?:подр\.?|подразделения)\s*[:.]?\s*(?P<code>\d{3}\s*[-–—]?\s*\d{3})(?!\d)', re.I)
AUTHORITY = re.compile(r'МВД|УМВ\b|ФМС|ОВД|УВД|ПОЛИЦ|ПАСПОРТ|МИЛИЦ', re.I)


def extract(notes):
    """Accept documented layouts, leaving contradictory/incomplete records for review."""
    text = ' '.join((notes or '').split())
    matches = list(RECORD.finditer(text))
    if not matches and not re.search(r'паспорт', text, re.I):
        return {}, ''
    if len(matches) != 1 or len(NUMBER.findall(text)) != 1:
        return {}, 'Формат не распознан или указано несколько паспортов'
    record = matches[0]
    tail = text[record.end():].strip(' ,;')
    labeled_codes = list(LABELED_CODE.finditer(tail))
    if len(labeled_codes) > 1:
        return {}, 'Указано несколько кодов подразделения'
    code_match = labeled_codes[0] if labeled_codes else CODE.search(tail)
    code = ''
    if code_match:
        digits = re.sub(r'\D', '', code_match['code'])
        code = digits[:3] + '-' + digits[3:]
        tail = tail[:code_match.start()].strip(' ,;')
    # A present but malformed label must not be swallowed as part of the issuer.
    if re.search(r'код\s+(?:подр|подразделения)', tail, re.I):
        return {}, 'Некорректный код подразделения'
    tail = re.sub(r'^выдан\s*:?\s*', '', tail, flags=re.I)
    issued_matches = list(re.finditer(DATE, tail))
    if not issued_matches:
        return {}, 'Не найдена дата выдачи'
    try:
        birthday = datetime.strptime(record['birth'].replace('/', '.'), '%d.%m.%Y').date()
        issued_dates = {datetime.strptime(item[0].replace('/', '.'), '%d.%m.%Y').date() for item in issued_matches}
    except ValueError:
        return {}, 'Некорректная дата'
    if len(issued_dates) != 1:
        return {}, 'Указаны разные даты выдачи'
    issued = issued_dates.pop()
    if not date(1900, 1, 1) <= birthday < issued <= date.today():
        return {}, 'Проверьте даты рождения и выдачи'
    # Supported orders: issue date + issuer OR issuer + issue date(s).
    first, last = issued_matches[0], issued_matches[-1]
    before = tail[:first.start()].strip(' ,;.')
    after = tail[last.end():].strip(' ,;.')
    between = tail[first.end():last.start()].strip(' ,;.') if len(issued_matches) > 1 else ''
    if between or bool(before) == bool(after):
        return {}, 'Порядок данных выдачи не распознан'
    authority = before or after
    if not 5 <= len(authority) <= 500 or not AUTHORITY.search(authority):
        return {}, 'Не распознано название органа выдачи'
    fields = dict(birthday=birthday, passport_number=re.sub(r'\s', '', record['number']),
                  passport_issued=issued, passport_issued_by=authority)
    if code:
        fields['passport_code'] = code
    return fields, ''


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
        elif key == 'passport_code':
            if re.sub(r'\D', '', current) != re.sub(r'\D', '', value):
                return {}, 'Код подразделения в карточке отличается от примечания'
        elif key == 'passport_issued_by':
            if ' '.join(current.split()).casefold() != str(value).casefold():
                return {}, 'Данные в карточке отличаются от примечания'
        elif current != value:
            return {}, 'Даты в карточке отличаются от примечания'
    return updates, ''
