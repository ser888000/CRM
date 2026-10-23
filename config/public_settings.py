"""HTTPS deployment behind the dedicated Caddy reverse proxy."""
from .ssh_settings import *

DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Gunicorn is bound to loopback; Caddy replaces this header on incoming requests.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
CSRF_TRUSTED_ORIGINS = ['https://crm.aborigen-tour.ru']
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 3600
