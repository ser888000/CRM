from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django import template
register=template.Library()
@register.filter
def money(value):
    if value is None or value=='':return '—'
    try:
        value=Decimal(value).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        return f'{value:,.2f}'.replace(',',' ').replace('.',',')
    except (InvalidOperation,ValueError,TypeError):return '—'
