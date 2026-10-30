"""Official evidence, strict principal matching; never use a dependent as an applicant."""
import hashlib
import io
import re
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from . import eta
from .models import ETAApplication,ETAOfficialNotice,AuditEvent

MAX_EML=2*1024*1024


class TextOnly(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','head'):self.hidden+=1
        if tag in ('br','p','div','tr','td','li','h1','h2','h3'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','head'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','div','tr','li'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def safe_body(message):
    part=message.get_body(preferencelist=('plain','html'))
    if part is None:return ''
    content=part.get_content()
    if not isinstance(content,str):return ''
    if part.get_content_subtype()=='html':
        parser=TextOnly();parser.feed(content);content=''.join(parser.parts)
    # No HTML, embedded images, links, scripts or control sequences in the UI/PDF.
    return '\n'.join(line.strip() for line in re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]','',content).splitlines() if line.strip())[:100000]


def extract(text,subject=''):
    # Only the principal applicant block. Any unsupported format stays for review.
    principal=re.split(r'(?im)^\s*(?:dependents?|children\s+(?:included|details)|accompanying\s+children)\b',text,maxsplit=1)[0]
    patterns={
        'number':r'(?:ETA\s*(?:Reference|Application)?\s*(?:Number|No\.?|Reference)|Reference\s*(?:Number|No\.?)|Application\s*(?:Number|No\.?))\s*[:#]\s*([A-Z0-9/-]{4,100})',
        'passport':r'Passport\s*(?:Number|No\.?)\s*[:#]\s*([A-Z0-9 ]{4,30})',
        'surname':r'(?:Surname|Family\s*Name)\s*:\s*([^\n]{1,150})',
        'given_names':r'(?:Other\s*Names?|Given\s*Names?|First\s*Names?)\s*:\s*([^\n]{1,150})',
    }
    identifiers={}
    for key,pattern in patterns.items():
        values=list(dict.fromkeys(re.findall(pattern,principal,re.I)))
        identifiers[key]=values[0].strip() if len(values)==1 else ''
    header=(subject+'\n'+principal[:3000]).upper()
    approval=bool(re.search(r'\bETA\s+APPROVAL\s+NOTICE\b',header))
    referral=bool(re.search(r'REFER(?:RED|RAL)|CONTACT.{0,50}IMMIGRATION|ADDITIONAL\s+(?:REVIEW|CONSIDERATION)|PENDING\s+APPROVAL',header))
    receipt=bool(re.search(r'ACKNOWLEDGEMENT|ACKNOWLEDGMENT|APPLICATION\s+(?:RECEIVED|RECEIPT)|CONFIRMATION\s+OF\s+RECEIPT',header))
    # Conflicting phrases, quoted thread or incomplete principal => no automatic decision.
    kind='unknown' if sum((approval,referral,receipt))!=1 else 'approval' if approval else 'referral' if referral else 'receipt'
    if re.search(r'(?im)^\s*(?:On .+wrote:|[- ]*Original Message[- ]*|From:|>)',text):kind='unknown'
    return kind,identifiers


def trusted_mail(message):
    if not settings.ETA_MAIL_AUTOMATIC_TRUST:return False
    domain=parseaddr(str(message.get('From','')))[1].rsplit('@',1)[-1].lower()
    if domain not in settings.ETA_MAIL_OFFICIAL_DOMAINS:return False
    # Trust only the FIRST Authentication-Results inserted by the configured mailbox
    # provider, never a matching header deeper in the message or a From display name.
    values=message.get_all('Authentication-Results',[])
    if not values or not settings.ETA_MAIL_AUTHSERV_ID:return False
    auth=str(values[0]);parts=auth.split(';')
    if parts[0].strip().lower()!=settings.ETA_MAIL_AUTHSERV_ID.lower():return False
    return any(re.search(r'\bdkim\s*=\s*pass\b',p,re.I) and re.search(r'\bheader\.d\s*=\s*'+re.escape(domain)+r'(?:\s|;|$)',p,re.I) for p in parts[1:])


def matching_applications(identifiers):
    if not all(identifiers.get(k) for k in ('number','passport','surname','given_names')):return []
    found=[]
    from django.db.models import Q
    candidates=ETAApplication.objects.filter(Q(application_number=identifiers['number'])|Q(application_number='',submission_started_at__isnull=False)).select_related('active_export','contract')
    for app in candidates:
        if not app.active_export_id:continue
        entry=next((r for r in app.active_export.payload['applicants'] if r['application_id']==str(app.pk)),None)
        if not entry:continue
        data=entry['data']
        if (eta.normalized(identifiers['passport'])==eta.normalized(data['passport']['number']) and
            eta.normalized(identifiers['surname'])==eta.normalized(data['person']['surname']) and
            eta.normalized(identifiers['given_names'])==eta.normalized(data['person']['given_names'])):found.append(app)
    return found


@transaction.atomic
@sensitive_variables()
def ingest(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_EML:raise ValidationError('Письмо должно быть EML размером до 2 МБ.')
    checksum=hashlib.sha256(raw).hexdigest()
    existing=ETAOfficialNotice.objects.filter(sha256=checksum).first()
    if existing:return existing
    try:
        message=BytesParser(policy=policy.default).parsebytes(raw)
        text=safe_body(message);kind,ids=extract(text,str(message.get('Subject','')))
        trusted=trusted_mail(message)
    except (ValueError,TypeError,LookupError,RecursionError):raise ValidationError('Невозможно безопасно прочитать письмо.') from None
    matches=matching_applications(ids)
    app=matches[0] if len(matches)==1 else None
    reason=''
    if kind=='unknown':reason='Неизвестный или противоречивый тип официального сообщения.'
    elif app is None:reason='Неоднозначное соответствие: нужны номер ETA, паспорт и ФИО основного заявителя.'
    elif not trusted:reason='Нужно проверить подлинность письма: доверенная DKIM-проверка почтового сервера не подтверждена.'
    notice=ETAOfficialNotice.objects.create(original=raw,sha256=checksum,safe_text=text,kind=kind,trusted=trusted,identifiers=ids,application=app,review_reason=reason)
    if not reason:
        try:accept_notice(notice,None)
        except ValidationError:
            notice.review_reason='Подача этого заявления в CRM не подтверждена; требуется ручная сверка.';notice.save(update_fields=['review_reason'])
        notice.refresh_from_db()
    return notice


@transaction.atomic
def accept_notice(notice,actor):
    notice=ETAOfficialNotice.objects.select_for_update().get(pk=notice.pk)
    if notice.accepted_at:return notice
    matches=matching_applications(notice.identifiers)
    if len(matches)!=1 or notice.kind not in ('approval','referral','receipt'):raise ValidationError('Письмо нельзя однозначно отнести к основному заявителю. Dependents не подтверждают одобрение ребёнка.')
    if actor is None and not notice.trusted:raise ValidationError('Нет подтверждения подлинности письма.')
    app=ETAApplication.objects.select_for_update().get(pk=matches[0].pk)
    # Mail is evidence of an already accepted application, never permission to submit.
    if not app.submission_started_at and not app.submission_authorized_at:raise ValidationError('Заявление не было подано через подтверждённое задание CRM. Нужна ручная сверка.')
    if app.application_number and app.application_number!=notice.identifiers['number']:raise ValidationError('Номер ETA отличается от сохранённого.')
    if not app.application_number:app.application_number=notice.identifiers['number']
    notice.application=app;notice.accepted_at=timezone.now();notice.accepted_by=actor;notice.review_reason='';notice.save()
    if app.status!='approved' and not (app.status=='referral' and notice.kind=='receipt'):
        app.status={'approval':'approved','referral':'referral','receipt':'under_review'}[notice.kind]
        app.portal_status={'approval':'ETA APPROVAL NOTICE','referral':'Referral / additional consideration','receipt':'Application received'}[notice.kind]
        app.stop_reason='' if notice.kind!='referral' else 'Получено официальное направление на дополнительное рассмотрение. Проверьте письмо.'
        if notice.kind=='approval':app.active_identity_key=None;app.transport_state='completed'
        elif notice.kind=='receipt' and app.worker_id:
            from datetime import timedelta
            if app.transport_state!='leased':app.transport_state='queued';app.transport_action='status';app.next_check_at=timezone.now()+timedelta(minutes=10)
        app.save()
    else:app.save(update_fields=['application_number'])
    AuditEvent.objects.create(actor=actor,object_type='crm.ETAApplication',object_id=str(app.pk),action='eta_official_notice',changes={'kind':notice.kind,'notice_id':str(notice.pk)})
    return notice


def pdf_copy(notice):
    """Safe text copy of official evidence, not a newly invented authorization."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from xml.sax.saxutils import escape
    from pathlib import Path
    font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not font.is_file():raise ValidationError('Установите fonts-dejavu-core для PDF-копии письма.')
    if 'ETA-DejaVu' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('ETA-DejaVu',str(font)))
    output=io.BytesIO();styles=getSampleStyleSheet();style=styles['Normal'];style.fontName='ETA-DejaVu';style.fontSize=9;style.leading=13
    label='ETA APPROVAL NOTICE — email text copy' if notice.kind=='approval' and notice.accepted_at else 'UNVERIFIED / NOT AN ETA APPROVAL — email text copy'
    story=[Paragraph(label,style),Paragraph('Original EML SHA-256: '+notice.sha256,style),Spacer(1,12)]
    for line in notice.safe_text.splitlines():
        for start in range(0,max(1,len(line)),2000):story.append(Paragraph(escape(line[start:start+2000]),style))
    SimpleDocTemplate(output).build(story)
    return output.getvalue()
