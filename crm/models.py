from decimal import Decimal
from urllib.parse import quote, urlsplit
from string import Formatter
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

class Customer(models.Model):
    surname=models.CharField('Фамилия',max_length=100,blank=True)
    given_name=models.CharField('Имя',max_length=100,blank=True)
    patronymic=models.CharField('Отчество',max_length=100,blank=True)
    main_phone=models.CharField('Основной телефон',max_length=100,blank=True)
    main_email=models.CharField('Основной email',max_length=250,blank=True)
    passport_number=models.CharField('Паспорт РФ: серия и номер',max_length=100,blank=True)
    passport_issued=models.DateField('Паспорт РФ: дата выдачи',null=True,blank=True)
    passport_issued_by=models.CharField('Паспорт РФ: кем выдан',max_length=500,blank=True)
    passport_code=models.CharField('Паспорт РФ: код подразделения',max_length=50,blank=True)
    name = models.CharField('ФИО заказчика',max_length=250)
    birthday = models.DateField('Дата рождения',null=True,blank=True)
    passport = models.TextField('Паспортные данные',blank=True)
    address = models.TextField('Адрес регистрации',blank=True)
    phones = models.TextField('Дополнительные телефоны (по одному в строке)',blank=True)
    emails = models.TextField('Дополнительные email (по одному в строке)',blank=True)
    class Meta: verbose_name='Заказчик'; verbose_name_plural='Заказчики'
    def __str__(self): return self.name

def booking_url(template,number):
    if not template or not number:
        return ''
    try:
        url=template.format(booking=quote(number,safe=''))
        if '{booking}' not in template and template.endswith(('=','/')):url+=quote(number,safe='')
        parts=urlsplit(url)
        if parts.scheme not in ('https','http') or not parts.hostname or parts.username or parts.password:
            return ''
        return url
    except (ValueError,KeyError,IndexError,AttributeError):
        return ''

class NamedReference(models.Model):
    name=models.CharField('Название',max_length=100,unique=True)
    class Meta:
        abstract=True
        ordering=['name']
    def __str__(self): return self.name

class ContractType(NamedReference):
    class Meta(NamedReference.Meta):
        verbose_name='Тип договора'
        verbose_name_plural='Типы договоров'

class PaymentMethod(NamedReference):
    class Meta(NamedReference.Meta):
        verbose_name='Способ оплаты'
        verbose_name_plural='Способы оплаты'

class Operator(models.Model):
    name = models.CharField('Название',max_length=200,unique=True)
    booking_url_template = models.CharField('Шаблон ссылки на бронь',max_length=1500,blank=True,help_text='Полная ссылка с https:// и {booking} вместо номера. Можно также адрес, заканчивающийся на = или / — номер добавится в конец. Пример: https://agency.pegast.ru/MyAccount/Bookings/?bi={booking}')
    def clean(self):
        super().clean()
        if self.booking_url_template:
            try:
                fields=[field for _,field,_,_ in Formatter().parse(self.booking_url_template) if field is not None]
                if any(field!='booking' for field in fields) or (not fields and not self.booking_url_template.endswith(('=','/'))) or not booking_url(self.booking_url_template,'TEST'):
                    raise ValueError
            except (ValueError,KeyError,IndexError,AttributeError):
                raise ValidationError({'booking_url_template':'Укажите полную ссылку с https:// и {booking} вместо номера, либо адрес, заканчивающийся на = или /.'})
    def booking_link(self,number):
        return booking_url(self.booking_url_template,number)
    class Meta: verbose_name='Туроператор'; verbose_name_plural='Туроператоры'
    def __str__(self): return self.name

class Tourist(models.Model):
    surname=models.CharField('Фамилия по паспорту',max_length=100,blank=True)
    given_name=models.CharField('Имя по паспорту',max_length=100,blank=True)
    passport_type=models.CharField('Тип паспорта',max_length=1,choices=[('0','Загранпаспорт'),('1','Российский')],blank=True)
    birthcountry=models.CharField('Страна рождения',max_length=100,blank=True)
    is_customer=models.BooleanField('Заказчик по данным Турвизора',default=False)
    name = models.CharField('ФИО по паспорту',max_length=250)
    customer = models.ForeignKey(Customer,on_delete=models.SET_NULL,null=True,blank=True,verbose_name='Карточка заказчика')
    gender = models.CharField('Пол',max_length=10,choices=[('male','Мужской'),('female','Женский')],blank=True)
    birthday = models.DateField('Дата рождения',null=True,blank=True)
    passport_number = models.CharField('Серия и номер паспорта',max_length=50,blank=True)
    issued = models.DateField('Дата выдачи',null=True,blank=True)
    expires = models.DateField('Действителен до',null=True,blank=True)
    issued_by = models.CharField('Кем выдан',max_length=250,blank=True)
    nationality = models.CharField('Гражданство',max_length=100,blank=True)
    class Meta: verbose_name='Турист'; verbose_name_plural='Туристы'
    def __str__(self): return self.name

class Contract(models.Model):
    updated_at=models.DateTimeField(auto_now=True,editable=False)
    tourvisor_id=models.CharField('ID онлайн-заявки Турвизора',max_length=40,unique=True,null=True,blank=True,editable=False)
    tourvisor_time=models.CharField('Время создания в Турвизоре',max_length=20,blank=True,editable=False)
    source_data=models.JSONField(default=dict,blank=True,editable=False)
    imported_at=models.DateTimeField('Последний импорт',null=True,blank=True,editable=False)
    tour_name=models.CharField('Название тура у ТО',max_length=500,blank=True)
    nights=models.PositiveIntegerField('Ночей',null=True,blank=True)
    adults=models.PositiveIntegerField('Взрослых',default=0)
    children=models.PositiveIntegerField('Детей',default=0)
    infants=models.PositiveIntegerField('Младенцев',default=0)
    source_currency=models.CharField('Валюта предложения',max_length=3,default='RUB')
    operator_link=models.URLField('Ссылка из Турвизора',max_length=2000,blank=True)
    number = models.CharField('Номер договора Турвизора',max_length=100,blank=True)
    date = models.DateField('Дата договора',default=timezone.localdate)
    customer = models.ForeignKey(Customer,on_delete=models.PROTECT,verbose_name='Заказчик')
    operator = models.ForeignKey(Operator,on_delete=models.PROTECT,verbose_name='Туроператор')
    contract_type = models.ForeignKey(ContractType,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Тип договора')
    country = models.CharField('Страна',max_length=100,blank=True)
    region = models.CharField('Регион',max_length=150,blank=True)
    departure = models.CharField('Город вылета',max_length=150,blank=True)
    start = models.DateField('Начало тура',null=True,blank=True)
    end = models.DateField('Окончание тура',null=True,blank=True)
    hotel = models.CharField('Отель',max_length=250,blank=True)
    room = models.CharField('Категория номера',max_length=200,blank=True)
    meal = models.CharField('Питание',max_length=100,blank=True)
    transfer = models.CharField('Трансфер',max_length=200,blank=True)
    insurance = models.CharField('Страховка',max_length=200,blank=True)
    services = models.TextField('Дополнительные услуги',blank=True)
    flights = models.TextField('Рейсы туда и обратно',blank=True)
    payment_method = models.ForeignKey(PaymentMethod,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Основной способ оплаты')
    operator_due = models.DateField('Срок оплаты ТО',null=True,blank=True)
    operator_paid = models.DateField('Дата полной оплаты ТО',null=True,blank=True)
    metrika_id = models.CharField('ID клиента Метрики',max_length=100,blank=True)
    notes = models.TextField('Примечание',blank=True)
    class Meta: verbose_name='Договор'; verbose_name_plural='Договоры'
    def __str__(self): return self.number or f'Договор №{self.pk}'
    def clean(self):
        if self.start and self.end and self.end < self.start: raise ValidationError('Окончание тура раньше начала')
    @property
    def amount(self): return self.lines.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    def balance(self,kind):
        p=self.payments.filter(kind=kind).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        r=self.payments.filter(kind=kind+'_refund').aggregate(s=Sum('amount'))['s'] or Decimal('0')
        return p-r
    @property
    def paid(self): return self.balance('customer')
    @property
    def cost(self): return self.balance('operator')
    @property
    def profit(self): return self.amount-self.cost
    @property
    def debt(self): return self.amount-self.paid

class Booking(models.Model):
    contract = models.ForeignKey(Contract,on_delete=models.CASCADE,related_name='bookings')
    number = models.CharField('Номер брони ТО',max_length=150)
    url = models.URLField('Ссылка на бронь',blank=True)
    @property
    def booking_link(self):
        url=self.contract.operator.booking_link(self.number) or self.url
        try:
            return url if urlsplit(url).scheme in ('http','https') else ''
        except ValueError:
            return ''
    def __str__(self): return self.number
    class Meta: verbose_name='Бронь ТО' ; verbose_name_plural='Брони ТО'

class ContractLine(models.Model):
    contract = models.ForeignKey(Contract,on_delete=models.CASCADE,related_name='lines')
    tourist = models.ForeignKey(Tourist,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Турист')
    description = models.CharField('Описание',max_length=250)
    source_tourist_key=models.CharField(max_length=100,blank=True,editable=False)
    amount = models.DecimalField('Сумма, ₽ (может быть отрицательной)',max_digits=14,decimal_places=2,default=0)
    class Meta: verbose_name='Строка договора'; verbose_name_plural='Строки договора'

class Payment(models.Model):
    KINDS=[('customer','Поступление от клиента'),('customer_refund','Возврат клиенту'),('operator','Оплата ТО'),('operator_refund','Возврат от ТО')]
    contract = models.ForeignKey(Contract,on_delete=models.PROTECT,related_name='payments',verbose_name='Договор')
    kind = models.CharField('Операция',max_length=30,choices=KINDS)
    date = models.DateField('Дата',default=timezone.localdate)
    amount = models.DecimalField('Сумма, ₽',max_digits=14,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    method = models.ForeignKey(PaymentMethod,on_delete=models.PROTECT,verbose_name='Способ оплаты')
    currency = models.CharField('Справочно: валюта оплаты ТО',max_length=3,blank=True)
    rate = models.DecimalField('Справочно: курс',max_digits=14,decimal_places=2,null=True,blank=True,validators=[MinValueValidator(Decimal('0.01'))])
    notes = models.TextField('Примечание',blank=True)
    class Meta: verbose_name='Финансовая операция'; verbose_name_plural='Финансы'
    def __str__(self):
        from .templatetags.money import money
        return f'{self.get_kind_display()}: {money(self.amount)} ₽'

class TaskTemplate(models.Model):
    name = models.CharField('Задача',max_length=250)
    anchor = models.CharField('От какой даты',max_length=20,choices=[('created','Создание договора'),('start','Начало тура'),('end','Окончание тура')])
    offset = models.IntegerField('Смещение в днях',default=0)
    active = models.BooleanField('Добавлять по умолчанию',default=True)
    order = models.PositiveIntegerField('Порядок в списке',default=0)
    copy_flights = models.BooleanField('Включить рейсы договора в описание',default=False)
    class Meta:
        verbose_name='Шаблон задачи'
        verbose_name_plural='Шаблоны задач'
        ordering=['order','pk']
    def __str__(self): return self.name

class Task(models.Model):
    title = models.CharField('Тип / название задачи',max_length=250)
    description = models.TextField('Описание',blank=True)
    due = models.DateField('Срок')
    done = models.BooleanField('Выполнено',default=False)
    customer = models.ForeignKey(Customer,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Заказчик')
    contract = models.ForeignKey(Contract,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Договор')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,verbose_name='Сотрудник')
    operator = models.ForeignKey(Operator,on_delete=models.PROTECT,null=True,blank=True,verbose_name='ТО (если задача без договора)')
    booking_number = models.CharField('Номер брони ТО (необязательно)',max_length=150,blank=True)
    template = models.ForeignKey(TaskTemplate,on_delete=models.SET_NULL,null=True,blank=True)
    origin_key = models.CharField(max_length=100,null=True,blank=True,unique=True,editable=False)
    class Meta: verbose_name='Задача'; verbose_name_plural='Задачи'; ordering=['done','due','pk']
    @property
    def tour_operator(self):
        return self.contract.operator if self.contract_id else self.operator
    @property
    def booking_entries(self):
        if self.booking_number:
            return [(self.booking_number,self.tour_operator.booking_link(self.booking_number) if self.tour_operator else '')]
        if self.contract_id:
            return [(b.number,b.booking_link) for b in self.contract.bookings.all()]
        return []
    def __str__(self): return self.title

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    at = models.DateTimeField(auto_now_add=True)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50)
    action = models.CharField(max_length=50)
    changes = models.JSONField(default=dict)
    class Meta: verbose_name='Изменение'; verbose_name_plural='История изменений'; ordering=['-at']


def normalize_location(value):
    import unicodedata
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().replace('ё','е').split())

class LocationReference(models.Model):
    code=models.CharField('Код из исходного справочника',max_length=40,unique=True)
    name=models.CharField('Название',max_length=100,unique=True)
    details=models.JSONField('Дополнительные данные исходного файла',default=dict,blank=True)
    class Meta:
        abstract=True
        ordering=['name']
    def __str__(self):return self.name
    @classmethod
    def match(cls,value):
        target=normalize_location(value)
        matches=[record for record in cls.objects.all() if normalize_location(record.name)==target]
        return matches[0] if len(matches)==1 else None

class DepartureCity(LocationReference):
    class Meta(LocationReference.Meta):
        verbose_name='Город вылета'
        verbose_name_plural='Города вылета'

class Country(LocationReference):
    class Meta(LocationReference.Meta):
        verbose_name='Страна'
        verbose_name_plural='Страны'

class Currency(models.Model):
    code=models.CharField('Код',max_length=3,unique=True)
    name=models.CharField('Название',max_length=100)
    class Meta:
        verbose_name='Валюта'
        verbose_name_plural='Валюты'
        ordering=['code']
    def __str__(self):return f'{self.code} · {self.name}'
