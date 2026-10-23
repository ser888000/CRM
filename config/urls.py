from django.contrib import admin
from django.urls import path
from crm import views,import_views
urlpatterns = [path('tourvisor/import/',import_views.import_order,name='tourvisor_import'),path('finances/',views.finances,name='finances'),path('admin/',admin.site.urls),path('',views.contracts,name='contracts'),path('tasks/',views.tasks,name='tasks'),path('tasks/reschedule/',views.reschedule,name='reschedule')]
