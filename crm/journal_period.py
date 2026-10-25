"""Shared bounded date selection for contracts and financial operations."""
from datetime import timedelta
from django.http import QueryDict
from django.utils import timezone


def prepare(params,saved=''):
    data=params.copy();previous=QueryDict(saved);today=timezone.localdate()
    if 'reset' in data:
        source=data if 'start' in data or 'end' in data or 'period' in data else previous
        data=QueryDict('',mutable=True)
        for key in ('start','end','period','sort'):
            if source.get(key):data[key]=source[key]
    if not any(key in data for key in ('start','end','period')):
        for key in ('start','end','period'):
            if previous.get(key):data[key]=previous[key]
    mode=data.get('period','')
    month_start=today.replace(day=1).isoformat()
    month_end=((today.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)).isoformat()
    if mode in ('today','tomorrow'):
        data['start']=data['end']=today.isoformat()
    elif mode=='month':
        data['start']=month_start;data['end']=month_end
    else:
        start=data.get('start','');end=data.get('end','')
        if not start and not end:start=end=today.isoformat()
        elif not start:start=end
        elif not end:end=start
        data['start']=start;data['end']=end
    data['period']='today' if data['start']==data['end']==today.isoformat() else 'month' if data['start']==month_start and data['end']==month_end else 'custom'
    data.pop('reset',None)
    return data


def has_value_filters(params,fields):
    return any(str(params.get(field,'')).strip() for field in fields)


def reset_link(path,params):
    data=QueryDict('',mutable=True)
    for key in ('start','end','period','status','sort'):
        if params.get(key):data[key]=params[key]
    data['reset']='1'
    return path+'?'+data.urlencode()
