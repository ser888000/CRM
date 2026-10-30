from .models import normalize_location


def matches(values,params):
    return all(not params.get('q_'+key,'').strip() or normalize_location(params['q_'+key][:250]) in normalize_location(str(value or '')) for key,value in values.items())


def decorate(columns,params):
    for column in columns:
        column['search']=params.get('q_'+column['key'],'')[:250]
        column['active']=column['active'] or bool(column['search'])
    return columns
