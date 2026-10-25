"""Create/reuse catalog identities, while historical snapshots remain on each line."""
from .models import Tourist,normalize_location

def identity(surname,given,patronymic,birthday,passport):
    name=normalize_location(' '.join([surname,given,patronymic]))
    return (name,str(birthday or ''),''.join(c for c in passport if c.isalnum()).casefold())

def attach_tourists(lines,source,report):
    from .legacy_history import string,date
    lookup={}
    for t in Tourist.objects.all():
        key=identity(t.name,'','',t.birthday,t.passport_number)
        lookup.setdefault(key,t)
    pending=[];reused=0
    for key,line in lines:
        raw=source[key];surname=string(raw.get('ADD_LAST_NAME'));given=string(raw.get('ADD_FIRST_NAME'));patronymic=string(raw.get('ADD_otchestvo'))
        if not surname and not given:continue
        birthday=date(raw.get('ADD_DATE_ROZDENIYA'));passport=' '.join(filter(None,[string(raw.get('ADD_PASPORT_SERIYA')),string(raw.get('ADD_NOMER_1'))]))
        person_key=identity(surname,given,patronymic,birthday,passport)
        if not passport and (not birthday or birthday.year==1900):person_key=(*person_key,key)
        if person_key not in lookup:
            gender=normalize_location(string(raw.get('ADD_POL')))
            t=Tourist(surname=surname[:100],given_name=given[:100],name=' '.join(filter(None,[surname,given,patronymic]))[:250],birthday=birthday,passport_number=passport[:50],gender='male' if gender in ('м','муж','мужской','male') else 'female' if gender in ('ж','жен','женский','female') else '',issued=date(raw.get('ADD_PASPORT_VYDAN_DATE')),expires=date(raw.get('ADD_PASPORT_SROK_DATE')),issued_by=string(raw.get('ADD_PASPORT_VYDAN_1'))[:250])
            lookup[person_key]=t;pending.append(t)
        else:reused+=1
        line.tourist=lookup[person_key]
    Tourist.objects.bulk_create(pending,batch_size=100)
    # Assign IDs explicitly: Django caches a ForeignKey set before its target was inserted.
    for _,line in lines:
        if line.tourist is not None:line.tourist_id=line.tourist.pk
    report['counts']['tourists_created']=len(pending);report['counts']['tourists_reused']=reused
