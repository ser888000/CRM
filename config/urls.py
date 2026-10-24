from django.contrib import admin
from django.urls import path
from crm import views,import_views,card_views,passport_ocr,customer_views
urlpatterns = [path('customers/new/',customer_views.create_customer,name='customer_create'),path('passport/recognize/',passport_ocr.recognize,name='passport_recognize'),path('contracts/new/',card_views.contract_card,name='contract_new'),path('contracts/<int:pk>/',card_views.contract_card,name='contract_card'),path('tourvisor/import/',import_views.import_order,name='tourvisor_import'),path('finances/',views.finances,name='finances'),path('admin/',admin.site.urls),path('',views.contracts,name='contracts'),path('tasks/',views.tasks,name='tasks'),path('tasks/reschedule/',views.reschedule,name='reschedule')]
