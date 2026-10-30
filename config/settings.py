import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-development-only-do-not-use-in-production')
if not DEBUG and SECRET_KEY == 'local-development-only-do-not-use-in-production':
    raise RuntimeError('Set DJANGO_SECRET_KEY for production')
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','crm']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','crm.update_middleware.UpdateMaintenanceMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'crm'/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
if os.getenv('POSTGRES_HOST'):
    DATABASES = {'default': {'ENGINE':'django.db.backends.postgresql','HOST':os.environ['POSTGRES_HOST'],'NAME':os.getenv('POSTGRES_DB','crm'),'USER':os.getenv('POSTGRES_USER','crm'),'PASSWORD':os.environ['POSTGRES_PASSWORD']}}
else:
    DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':os.getenv('CRM_DATABASE_PATH',str(BASE_DIR/'db.sqlite3'))}}
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR/'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/admin/login/'
SESSION_COOKIE_HTTPONLY = True
if not DEBUG:
    SESSION_COOKIE_SECURE = os.getenv('DJANGO_COOKIE_SECURE','1')=='1'
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
FORMAT_MODULE_PATH=['crm.formats']
USE_THOUSAND_SEPARATOR=True

# Separate high-entropy bearer credentials; no secrets are shipped to a browser.
ETA_EXECUTOR_ENABLED = os.getenv('ETA_EXECUTOR_ENABLED', '0') == '1'
ETA_WORKER_TOKEN = os.getenv('ETA_WORKER_TOKEN', '')
ETA_MAIL_TOKEN = os.getenv('ETA_MAIL_TOKEN', '')
ETA_MAIL_OFFICIAL_DOMAINS = tuple(filter(None, os.getenv('ETA_MAIL_OFFICIAL_DOMAINS', '').lower().split(',')))
ETA_MAIL_AUTHSERV_ID = os.getenv('ETA_MAIL_AUTHSERV_ID', '')
ETA_MAIL_AUTOMATIC_TRUST = os.getenv('ETA_MAIL_AUTOMATIC_TRUST', '0') == '1'

# v1 PDF results use bounded base64 uploads; API enforces a smaller per-role limit.
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
