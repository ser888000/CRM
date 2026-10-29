from django import forms
from .models import Tourist

class ETAPreparationForm(forms.Form):
    surname=forms.CharField(label='Фамилия загранпаспорта (латиницей)',max_length=100,required=False)
    given_names=forms.CharField(label='Имена загранпаспорта (латиницей)',max_length=100,required=False)
    gender=forms.ChoiceField(label='Пол',choices=[('','Выберите'),('male','Мужской'),('female','Женский')],required=False)
    birthday=forms.DateField(label='Дата рождения',required=False)
    nationality=forms.CharField(label='Гражданство (как в паспорте)',max_length=100,required=False)
    birth_country=forms.CharField(label='Страна рождения',max_length=100,required=False)
    child_occupation=forms.CharField(label='Занятие несовершеннолетнего, если требует портал (без автоматического ответа)',max_length=100,required=False)
    passport_type=forms.ChoiceField(label='Тип документа',choices=[('','Выберите'),('0','Загранпаспорт'),('1','Паспорт РФ')],required=False)
    passport_number=forms.CharField(label='Номер загранпаспорта',max_length=50,required=False)
    passport_issued=forms.DateField(label='Дата выдачи',required=False)
    passport_expires=forms.DateField(label='Действителен до',required=False)
    home_address=forms.CharField(label='Домашний адрес заказчика (полный исходный текст)',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    home_city=forms.CharField(label='Город проживания (если выделен из адреса)',max_length=100,required=False)
    home_region=forms.CharField(label='Регион проживания (если выделен из адреса)',max_length=100,required=False)
    home_country=forms.CharField(label='Страна проживания (если выделена из адреса)',max_length=100,required=False)
    phone=forms.CharField(label='Телефон туриста с кодом страны',max_length=40,required=False)
    arrival_date=forms.DateField(label='Дата прибытия именно в Шри-Ланку',required=False)
    departure_date=forms.DateField(label='Дата выезда из Шри-Ланки',required=False)
    departure_airport=forms.CharField(label='Аэропорт вылета прибывающего рейса',max_length=150,required=False)
    arrival_airport=forms.CharField(label='Аэропорт прибытия в Шри-Ланку',max_length=150,required=False)
    airline=forms.CharField(label='Авиакомпания прибывающего рейса',max_length=150,required=False)
    flight_number=forms.CharField(label='Номер прибывающего рейса',max_length=50,required=False)
    hotel_name=forms.CharField(label='Название отеля',max_length=250,required=False)
    hotel_address=forms.CharField(label='Полный адрес отеля (если известен; иначе найдёт исполнитель)',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    travel_confirmed=forms.BooleanField(label='Проверены даты прибытия/выезда, прибывающий рейс и адрес отеля',required=False)
    identity_confirmed=forms.BooleanField(label='Сведения туриста сверены с действующим загранпаспортом',required=False)
    previous_visas=forms.CharField(label='Предыдущие визы/ETA и пребывания: подтверждённые сведения, либо явно «нет»',max_length=3000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    previous_visas_confirmed=forms.BooleanField(label='Сведения о предыдущих визах подтверждены туристом',required=False)
    travel_last_14_days=forms.CharField(label='Страны пребывания за последние 14 дней: подтверждённые сведения',max_length=3000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    travel_history_confirmed=forms.BooleanField(label='История за 14 дней подтверждена туристом',required=False)
    portal_rules_checked=forms.BooleanField(label='Проверены актуальные вопросы, условия и правила для детей официального портала',required=False)
    parent_tourist=forms.ModelChoiceField(label='Родитель / законный представитель из договора (для ребёнка)',queryset=Tourist.objects.none(),required=False)
    guardian_details=forms.CharField(label='Родитель / представитель, если его нет среди туристов договора',max_length=500,required=False)
    relationship=forms.CharField(label='Родственная связь / полномочия представителя',max_length=250,required=False)
    expected_fee=forms.DecimalField(label='Ожидаемый сбор, если известен (неизвестен — оставить пустым)',max_digits=12,decimal_places=2,min_value=0,required=False)
    expected_fee_currency=forms.CharField(label='Валюта ожидаемого сбора (ISO: USD и т. п.)',max_length=3,required=False)
    def __init__(self,*args,contract,tourist,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['parent_tourist'].queryset=Tourist.objects.filter(contractline__contract=contract).exclude(pk=tourist.pk).distinct()
        for field in self.fields.values():
            if isinstance(field,forms.DateField):field.widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'})

class ETAAnswerForm(forms.Form):
    question=forms.CharField(label='Точная формулировка вопроса декларации / анкеты',max_length=1000,required=False)
    answer=forms.CharField(label='Подтверждённый ответ',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':2}))
    confirmed=forms.BooleanField(label='Ответ подтверждён туристом',required=False)

ETAAnswerSet=forms.formset_factory(ETAAnswerForm,extra=3,max_num=50,validate_max=True,absolute_max=50,can_delete=True)

class ETAResultForm(forms.Form):
    result_file=forms.FileField(label='JSON результата (включая Approval Notice в base64, если получен)',widget=forms.FileInput(attrs={'accept':'.json,application/json'}))
    checked=forms.BooleanField(label='Я проверил(а), что результаты относятся к этим туристам и отражают фактический ответ портала')
    def clean_result_file(self):
        file=self.cleaned_data['result_file']
        if file.size>16*1024*1024:raise forms.ValidationError('Максимальный размер JSON — 16 МБ.')
        return file

class ETAAuthorizeForm(forms.Form):
    version=forms.CharField(widget=forms.HiddenInput)
    summary_reviewed=forms.BooleanField(label='Проверена фактическая сводка портала для этого туриста')
    address_reviewed=forms.BooleanField(label='Адрес в сводке соответствует адресу заказчика, включая перевод и выделение города/региона/страны')
    conditions_confirmed=forms.BooleanField(label='Необходимые условия и декларации прочитаны и подтверждены')
    fee=forms.DecimalField(label='Фактический сбор из сводки',max_digits=12,decimal_places=2,min_value=0)
    currency=forms.RegexField(r'^[A-Z]{3}$',label='Валюта фактического сбора')

class ETAReturnForm(forms.Form):
    version=forms.CharField(widget=forms.HiddenInput)
    portal_checked_no_submission=forms.BooleanField(label='Проверено на портале: заявление не принято, номера нет. Можно вернуть на подготовку')
    reason=forms.CharField(label='Причина возврата',min_length=5,max_length=500)
