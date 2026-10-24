from django.contrib.auth.decorators import login_required,permission_required
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from .card_forms import CustomerCardForm
from .card_views import audit

@login_required
@permission_required('crm.add_customer',raise_exception=True)
@require_POST
@never_cache
@sensitive_post_parameters()
@sensitive_variables()
@transaction.atomic
def create_customer(request):
    form=CustomerCardForm(request.POST,prefix='customer-new')
    if not form.is_valid():return JsonResponse({'errors':form.errors.get_json_data()},status=400)
    customer=form.save();audit(request.user,customer,{},'created')
    return JsonResponse({'id':customer.pk,'name':customer.name})
