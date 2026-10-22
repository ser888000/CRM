from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

class Customer(models.Model):
    name = models.CharField('ФИО заказчика',max_length=250)
    birthday = models.DateField('Дата рождения',null=True,blank=True)
    passport = models.TextField('Паспортные данные',blank=True)
    address = models.TextField('Адрес регистрации',blank=True)
    phones = models.TextField('Телефоны (по одному в строке)',blank=True)
    emails = models.TextField('Email (по одному в строке)',blank=True)
    class Meta: verbose_name='Заказчик'; verbose_name_plural='Заказчики'
    def __str__(self): return self.name

class Operator(models.Model):
    name = models.CharField('Название',max_length=200,unique=True)
    class Meta: verbose_name='Туроператор'; verbose_name_plural='Туроператоры'
    def __str__(self): return self.name

class Tourist(models.Model):
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
    number = models.CharField('Номер договора Турвизора',max_length=100,blank=True)
    date = models.DateField('Дата договора',default=timezone.localdate)
    customer = models.ForeignKey(Customer,on_delete=models.PROTECT,verbose_name='Заказчик')
    operator = models.ForeignKey(Operator,on_delete=models.PROTECT,verbose_name='Туроператор')
    contract_type = models.CharField('Тип договора',max_length=100,blank=True)
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
    payment_method = models.CharField('Основной способ оплаты',max_length=100,blank=True)
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
    class Meta: verbose_name='Бронь ТО'; verbose_name_plural='Брони ТО'

class ContractLine(models.Model):
    contract = models.ForeignKey(Contract,on_delete=models.CASCADE,related_name='lines')
    tourist = models.ForeignKey(Tourist,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Турист')
    description = models.CharField('Описание',max_length=250)
    amount = models.DecimalField('Сумма, ₽ (может быть отрицательной)',max_digits=14,decimal_places=2,default=0)
    class Meta: verbose_name='Строка договора'; verbose_name_plural='Строки договора'

class Payment(models.Model):
    KINDS=[('customer','Поступление от клиента'),('customer_refund','Возврат клиенту'),('operator','Оплата ТО'),('operator_refund','Возврат от ТО')]
    contract = models.ForeignKey(Contract,on_delete=models.PROTECT,related_name='payments',verbose_name='Договор')
    kind = models.CharField('Операция',max_length=30,choices=KINDS)
    date = models.DateField('Дата',default=timezone.localdate)
    amount = models.DecimalField('Сумма, ₽',max_digits=14,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    method = models.CharField('Способ оплаты',max_length=100)
    currency = models.CharField('Справочно: валюта оплаты ТО',max_length=3,blank=True)
    rate = models.DecimalField('Справочно: курс',max_digits=14,decimal_places=6,null=True,blank=True,validators=[MinValueValidator(Decimal('0.000001'))])
    notes = models.TextField('Примечание',blank=True)
    class Meta: verbose_name='Финансовая операция'; verbose_name_plural='Финансы'
    def __str__(self): return f'{self.get_kind_display()}: {self.amount} ₽'

class TaskTemplate(models.Model):
    name = models.CharField('Задача',max_length=250)
    anchor = models.CharField('От какой даты',max_length=20,choices=[('created','Создание договора'),('start','Начало тура'),('end','Окончание тура')])
    offset = models.IntegerField('Смещение в днях',default=0)
    active = models.BooleanField('Добавлять по умолчанию',default=True)
    class Meta: verbose_name='Шаблон задачи'; verbose_name_plural='Шаблоны задач'
    def __str__(self): return self.name

class Task(models.Model):
    title = models.CharField('Тип / название задачи',max_length=250)
    description = models.TextField('Описание',blank=True)
    due = models.DateField('Срок')
    done = models.BooleanField('Выполнено',default=False)
    customer = models.ForeignKey(Customer,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Заказчик')
    contract = models.ForeignKey(Contract,on_delete=models.PROTECT,null=True,blank=True,verbose_name='Договор')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,verbose_name='Сотрудник')
    template = models.ForeignKey(TaskTemplate,on_delete=models.SET_NULL,null=True,blank=True)
    origin_key = models.CharField(max_length=100,null=True,blank=True,unique=True,editable=False)
    class Meta: verbose_name='Задача'; verbose_name_plural='Задачи'; ordering=['done','due','pk']
    def __str__(self): return self.title

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True)
    at = models.DateTimeField(auto_now_add=True)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50)
    action = models.CharField(max_length=50)
    changes = models.JSONField(default=dict)
    class Meta: verbose_name='Изменение'; verbose_name_plural='История изменений'; ordering=['-at']
