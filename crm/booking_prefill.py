"""Staff-only synthetic-data probe for the agency's Tourvisor booking page."""
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

ORIGINS={'https://aborigen-tour.ru','https://www.aborigen-tour.ru'}

@require_GET
@never_cache
def demo(request):
    origin=request.headers.get('Origin','')
    if origin not in ORIGINS:
        return JsonResponse({'error':'Источник не разрешён.'},status=403)
    allowed=request.user.is_authenticated and request.user.is_active and request.user.has_perm('crm.view_contract')
    response=JsonResponse({'enabled':False},status=403) if not allowed else JsonResponse({
        'enabled':True,'test_only':True,
        'customer':{'Name':'Тестовый Заказчик Примерович','Phone':'+79990000000','Email':'test@example.invalid','Address':'Тестовый адрес','Birthday':'01.01.1980','PassportNumber':'0000 000001','PassportIssue':'01.02.2020','PassportAuthority':'Тестовый орган выдачи','PassportAuthorityCode':'000-000'},
        'tourists':[
            {'SURNAME':'TESTOV','NAME':'IVAN','BIRTHDAY':'01.01.1980','PASSPORTNUMBER':'00 0000001','PASSPORTISSUE':'01.02.2020','PASSPORTEXPIRY':'01.02.2030','PASSPORTAUTHORITY':'TEST'},
            {'SURNAME':'PROBNY','NAME':'PETR','BIRTHDAY':'02.02.1982','PASSPORTNUMBER':'00 0000002','PASSPORTISSUE':'01.02.2020','PASSPORTEXPIRY':'01.02.2030','PASSPORTAUTHORITY':'TEST'},
        ]})
    response['Access-Control-Allow-Origin']=origin
    response['Access-Control-Allow-Credentials']='true'
    response['Vary']='Origin, Cookie'
    response['X-Content-Type-Options']='nosniff'
    return response
