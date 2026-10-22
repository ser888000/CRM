from django.contrib import admin
from django.urls import path
from crm import views
urlpatterns = [path('admin/',admin.site.urls),path('',views.contracts,name='contracts'),path('tasks/',views.tasks,name='tasks'),path('tasks/reschedule/',views.reschedule,name='reschedule')]
