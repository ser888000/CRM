"""Owner-approved legacy migration corrections; source IDs are not new database IDs."""
import re
from .models import normalize_location
PAYMENT_NAMES={35:'Тинькофф Интернет',36:'Касса наличные',37:'Касса чек',40:'Тинькофф р/с',41:'Тинькофф QR',42:'Сбербанк р/с',43:'Сбербанк QR',44:'Альфа Банк р/с',51:'Uniteller АББ Интернет',52:'Зачет',53:'МИР туроператору',54:'СБП'}
DOCUMENT_METHODS={normalize_location(k):v for k,v in {'Интернет':'Тинькофф Интернет','Наличные':'Касса наличные','Касса':'Касса чек','QR':'Тинькофф QR','СБП':'СБП','Счет':'Счет','Терминал':'Терминал','Кредит':'Кредит','МИР':'МИР'}.items()}

def country(value):return 'Таиланд' if normalize_location(value)=='тайланд' else value

def departure(value):return 'Кемерово' if re.fullmatch(r'кемерово\s*/\s*новосибирск',normalize_location(value)) else value

def nights(value):
    match=re.match(r'^(\d{1,2})(?=\s|$)',value.strip())
    return int(match[1]) if match else None
