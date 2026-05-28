import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-change-in-production')
DEBUG      = os.getenv('DEBUG', 'True') == 'True'

# ── Hosts ──────────────────────────────────────────────────────────────────────
# In production, set ALLOWED_HOSTS env var to your deployed domain, e.g.:
# ALLOWED_HOSTS=breathe-esg.up.railway.app,api.breathe-esg.com
_raw_hosts = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1')
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(',') if h.strip()]

# ── Apps ───────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'app_ingestion',
]
CSRF_TRUSTED_ORIGINS = [
    o.strip() 
    for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') 
    if o.strip()
]

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',          # Must be first
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',      # Static files in production
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF      = 'breathe_esg.urls'
WSGI_APPLICATION  = 'breathe_esg.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS'   : [],
    'APP_DIRS': True,
    'OPTIONS' : {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

# ── Database ───────────────────────────────────────────────────────────────────
# In production (Railway / Render), set DATABASE_URL env var.
# Locally, falls back to the explicit psycopg2 config below.
_database_url = os.getenv('DATABASE_URL')

if _database_url:
    # Railway / Render / Heroku provide DATABASE_URL — parse it
    import re
    _m = re.match(
        r'postgres(?:ql)?://(?P<user>[^:]+):(?P<password>[^@]*)@(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<name>.+)',
        _database_url
    )
    if _m:
        DATABASES = {
            'default': {
                'ENGINE'  : 'django.db.backends.postgresql',
                'NAME'    : _m.group('name'),
                'USER'    : _m.group('user'),
                'PASSWORD': _m.group('password'),
                'HOST'    : _m.group('host'),
                'PORT'    : _m.group('port') or '5432',
            }
        }
    else:
        raise ValueError(f"Could not parse DATABASE_URL: {_database_url}")
else:
    DATABASES = {
        'default': {
            'ENGINE'  : 'django.db.backends.postgresql',
            'NAME'    : os.getenv('DB_NAME',     'breathe_esg'),
            'USER'    : os.getenv('DB_USER',     'breathe_user'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'breathe123'),
            'HOST'    : os.getenv('DB_HOST',     'localhost'),
            'PORT'    : os.getenv('DB_PORT',     '5432'),
        }
    }

# ── Auth ───────────────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalisation ───────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Asia/Kolkata'
USE_I18N      = True
USE_TZ        = True

# ── Static files ───────────────────────────────────────────────────────────────
STATIC_URL  = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
# WhiteNoise compression + caching in production
STATICFILES_STORAGE = (
    'whitenoise.storage.CompressedManifestStaticFilesStorage'
    if not DEBUG else
    'django.contrib.staticfiles.storage.StaticFilesStorage'
)

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── CORS ───────────────────────────────────────────────────────────────────────
# In production, set CORS_ALLOWED_ORIGINS env var (comma-separated list of
# front-end URLs), e.g.:
# CORS_ALLOWED_ORIGINS=https://breathe-esg.vercel.app,https://app.breathe-esg.com
_cors_env = os.getenv('CORS_ALLOWED_ORIGINS', '')

if _cors_env:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(',') if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
else:
    # Dev fallback — allow common local dev ports
    CORS_ALLOWED_ORIGINS = [
        'http://localhost:5173',
        'http://localhost:5174',
        'http://localhost:3000',
        'http://127.0.0.1:5173',
        'http://127.0.0.1:5174',
        'http://127.0.0.1:3000',
    ]
    CORS_ALLOW_ALL_ORIGINS = DEBUG   # In dev only

CORS_ALLOW_CREDENTIALS = True

# ── REST Framework ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # 'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# ── Logging ────────────────────────────────────────────────────────────────────
LOGGING = {
    'version'           : 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style' : '{',
        },
    },
    'handlers': {
        'console': {
            'class'    : 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level'   : 'INFO',
    },
    'loggers': {
        'app_ingestion': {
            'handlers'  : ['console'],
            'level'     : 'DEBUG' if DEBUG else 'INFO',
            'propagate' : False,
        },
    },
}

# ── Upload limits ──────────────────────────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800