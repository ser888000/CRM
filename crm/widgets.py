from django.forms import TextInput

class LocationInput(TextInput):
    template_name='crm/widgets/location_input.html'
    def __init__(self,model,attrs=None):
        self.reference_model=model
        super().__init__(attrs)
    def get_context(self,name,value,attrs):
        context=super().get_context(name,value,attrs)
        context['widget']['suggestions']=list(self.reference_model.objects.order_by('name').values_list('name',flat=True))
        context['widget']['attrs'].update({'autocomplete':'off','role':'combobox','aria-autocomplete':'list','aria-expanded':'false'})
        context['widget']['suggestions_id']=context['widget']['attrs'].get('id',name)+'_locations'
        return context
    class Media:
        js=['crm/location_input.js']
        css={'all':['crm/location_input.css']}
