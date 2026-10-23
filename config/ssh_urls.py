from django.urls import re_path
from django.views.static import serve
from django.conf import settings
from .urls import urlpatterns
urlpatterns=[re_path(r'^static/(?P<path>.*)$',serve,{'document_root':settings.STATIC_ROOT})]+urlpatterns
