from django.contrib.auth.decorators import login_required,permission_required
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from .models import Tourist,normalize_location

@login_required
@permission_required('crm.view_tourist',raise_exception=True)
@never_cache
def search(request):
    query=normalize_location(request.GET.get('q','')[:250])
    if len(query)<2:return JsonResponse({'choices':[]})
    values=[]
    for key,name,birthday in Tourist.objects.filter(is_hidden=False).order_by('name','pk').values_list('pk','name','birthday'):
        if query not in normalize_location(name):continue
        values.append({'id':key,'label':name+(' · '+birthday.strftime('%d.%m.%Y') if birthday else '')})
        if len(values)==30:break
    return JsonResponse({'choices':values})
