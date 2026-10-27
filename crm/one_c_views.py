"""Administrator-only test export; never writes business records or connects to 1C."""
import io
import re
from django import forms
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .financial_queries import with_financials
from .models import Contract, Payment
from .one_c_export import build_plan, package_bytes
from .update_views import require_admin


class TestExportForm(forms.Form):
    year = forms.IntegerField(label='Год клиентских операций', min_value=1900, max_value=2100, initial=2026)
    contracts = forms.MultipleChoiceField(label='Договоры для теста', widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['contracts'].choices = choices

    def clean_contracts(self):
        values = list(set(map(int, self.cleaned_data['contracts'])))
        if len(values) > 20:
            raise forms.ValidationError('Для первого теста выберите не больше 20 договоров.')
        return values


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def page(request):
    require_admin(request.user)
    try:
        year = int(request.POST.get('year') or request.GET.get('year', '2026'))
    except ValueError:
        year = 2026
    year = max(1900, min(year, 2100))
    data = request.POST if request.method == 'POST' else request.GET
    query = data.get('q', '').strip()[:100]
    # Selection travels with the search form, so another number never drops
    # previously selected contracts. Keep it scoped to this page, not a session.
    selected = data.getlist('contracts') if not data.get('clear') else []
    selected_ids = [int(value) for value in selected[:100]
                    if value.isdecimal() and len(value) <= 18]
    queryset = with_financials(Contract.objects.select_related('customer'))
    queryset = queryset.filter(Q(date__year=year) | Q(pk__in=Payment.objects.filter(
        date__year=year, kind__in=['customer', 'customer_refund']).values('contract_id')))
    results = queryset
    if query:
        numbers = [value.strip() for value in re.split(r'[,;\n]+', query) if value.strip()]
        if len(numbers) > 1:
            # Explicit multiple numbers are exact, avoiding unrelated substring matches.
            results = results.filter(number__in=numbers)
        else:
            results = results.filter(number__icontains=query)
    selected_contracts = list(queryset.filter(pk__in=selected_ids).order_by('-date', '-pk'))
    candidates = list(results.order_by('-date', '-pk')[:20])
    selected_keys = {c.pk for c in selected_contracts}
    candidates = selected_contracts + [c for c in candidates if c.pk not in selected_keys]
    choices = [(str(c.pk), f'{c.number or c.pk} · {c.date:%d.%m.%Y} · {c.customer.name} · {c.amount:,.2f} ₽') for c in candidates]
    form_data = None
    if request.method == 'POST' or selected:
        form_data = data.copy()
        form_data.setlist('contracts', selected)
    form = TestExportForm(form_data, choices=choices, initial={'year': year})
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                plan = build_plan(form.cleaned_data['contracts'], form.cleaned_data['year'])
                content = package_bytes(plan)
        except ValueError as exc:
            form.add_error(None, str(exc))
        else:
            response = FileResponse(io.BytesIO(content), as_attachment=True,
                filename=f'crm-1c-test-{year}.zip', content_type='application/zip')
            response['X-Content-Type-Options'] = 'nosniff'
            response['Cache-Control'] = 'private, no-store'
            return response
    return render(request, 'crm/one_c_export.html', {'form': form, 'year': year, 'query': query,
        'selected_count': len(selected_keys)})
