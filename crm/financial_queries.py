"""Correlated sums avoid join multiplication and per-row financial queries."""
from decimal import Decimal
from django.db.models import OuterRef,Subquery,Sum,Case,When,F,Value,DecimalField,ExpressionWrapper
from django.db.models.functions import Coalesce
from .models import ContractLine,Payment
MONEY=DecimalField(max_digits=24,decimal_places=2)

def with_financials(queryset):
    lines=ContractLine.objects.filter(contract_id=OuterRef('pk')).order_by().values('contract_id').annotate(total=Sum('amount')).values('total')[:1]
    def payments(kind):
        return Payment.objects.filter(contract_id=OuterRef('pk'),kind__in=[kind,kind+'_refund']).order_by().values('contract_id').annotate(total=Sum(Case(When(kind=kind,then=F('amount')),default=-F('amount'),output_field=MONEY))).values('total')[:1]
    zero=Value(Decimal('0'),output_field=MONEY)
    queryset=queryset.annotate(_line_total=Coalesce(Subquery(lines,output_field=MONEY),zero),_customer_net=Coalesce(Subquery(payments('customer'),output_field=MONEY),zero),_operator_net=Coalesce(Subquery(payments('operator'),output_field=MONEY),zero))
    return queryset.annotate(_financial_amount=ExpressionWrapper(F('_line_total')+F('legacy_amount_adjustment'),output_field=MONEY),_financial_cost=ExpressionWrapper(F('_operator_net')+F('opening_operator_paid'),output_field=MONEY))
