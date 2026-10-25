from django.forms import TextInput

class LocationInput(TextInput):
    template_name='crm/widgets/location_input.html'
    def __init__(self,model,attrs=None):
        self.reference_model=model
        super().__init__(attrs)
    def get_context(self,name,value,attrs):
        context=super().get_context(name,value,attrs)
        context['widget']['suggestions']=list((self.reference_model.objects.filter(is_hidden=False) if hasattr(self.reference_model,'sort_order') else self.reference_model.objects.filter(is_hidden=False).order_by('name')).values_list('name',flat=True))
        context['widget']['attrs'].update({'autocomplete':'off','role':'combobox','aria-autocomplete':'list','aria-expanded':'false'})
        context['widget']['suggestions_id']=context['widget']['attrs'].get('id',name)+'_locations'
        return context
    class Media:
        js=['crm/location_input.js']
        css={'all':['crm/location_input_v2.css']}

class MoneyInput(TextInput):
    def format_value(self,value):
        from decimal import Decimal
        from .templatetags.money import money
        if isinstance(value,(Decimal,int,float)):
            return money(value)
        return super().format_value(value)
