"""Small per-user display preferences; no business data or administrative permissions."""
import json
import re
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .models import UserInterfacePreference

THEMES=('office','accounting','spreadsheet')
TABLES=('contracts','customers','finances','tasks')


def value(pref):
    return {'theme':pref.theme if pref and pref.theme in THEMES else 'accounting','column_widths':pref.column_widths if pref else {}}


def context(request):
    if not request.user.is_authenticated:return {'ui_preferences':value(None)}
    return {'ui_preferences':value(UserInterfacePreference.objects.filter(user=request.user).first())}


@login_required
@never_cache
@require_http_methods(['GET','POST'])
@transaction.atomic
def preferences(request):
    if request.method=='GET':return JsonResponse(value(UserInterfacePreference.objects.filter(user=request.user).first()))
    try:
        if len(request.body)>32768:raise ValueError()
        data=json.loads(request.body)
        if not isinstance(data,dict) or not data or set(data)-{'theme','table','widths'}:raise ValueError()
        if 'theme' in data and data['theme'] not in THEMES:raise ValueError()
        if ('table' in data)!=('widths' in data):raise ValueError()
        if 'table' in data:
            if data['table'] not in TABLES:raise ValueError()
            widths=data['widths']
            if widths is not None and (not isinstance(widths,dict) or len(widths)>60 or any(not re.fullmatch(r'[a-z_]{1,60}',key) or type(width) is not int or not 48<=width<=1200 for key,width in widths.items())):raise ValueError()
    except (ValueError,TypeError,UnicodeError):return JsonResponse({'error':'Некорректные настройки интерфейса.'},status=400)
    pref,_=UserInterfacePreference.objects.get_or_create(user=request.user)
    pref=UserInterfacePreference.objects.select_for_update().get(pk=pref.pk)
    if 'theme' in data:pref.theme=data['theme']
    if 'table' in data:
        tables=dict(pref.column_widths)
        if data['widths'] is None:tables.pop(data['table'],None)
        else:tables[data['table']]={**tables.get(data['table'],{}),**data['widths']}
        pref.column_widths=tables
    pref.save()
    return JsonResponse(value(pref))
