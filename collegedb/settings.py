"""
CollegeDB settings.

Single settings file on purpose: a small ITS team should be able to read the
whole configuration in one sitting. Environment-specific values come from
.env (see .env.example).
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    DB_FALLBACK_SQLITE=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me-before-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # CollegeDB apps
    "core",
    "workflow",
    "documents",
    "admissions",
    "academics",
    "finaid",
    "student_accounts",
    "hr",
    "finance",
    "advancement",
]

# django.contrib.postgres powers trigram duplicate-person search on PostgreSQL.
# It imports psycopg at startup, so it must be left out on the SQLite fallback
# (where dedup degrades to substring matching anyway).
if not env("DB_FALLBACK_SQLITE"):
    INSTALLED_APPS.insert(6, "django.contrib.postgres")

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Exposes the acting user to the audit layer (core/audit.py).
    "core.middleware.CurrentUserMiddleware",
]

ROOT_URLCONF = "collegedb.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.nav",
            ],
        },
    },
]

WSGI_APPLICATION = "collegedb.wsgi.application"

# PostgreSQL is the supported target (trigram duplicate matching needs it).
# DB_FALLBACK_SQLITE=1 exists only so the app can boot on a machine without
# Postgres; the dedup service degrades to icontains matching there.
if env("DB_FALLBACK_SQLITE"):
    (BASE_DIR / "var").mkdir(exist_ok=True)  # fresh clones don't have var/ yet
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "var" / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": env.db(
            "DATABASE_URL",
            default="postgres://collegedb:collegedb@localhost:5432/collegedb",
        )
    }

AUTH_USER_MODEL = "core.User"

# --- Authentication -------------------------------------------------------
# Local accounts today. The SSO swap point: add mozilla-django-oidc (OIDC) or
# python3-saml (SAML) here later and map the IdP subject/claims onto
# User.username / User.sso_subject. Person.user is the only coupling between
# identity and data, so no data-model change is needed for SSO.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "var" / "staticfiles"
WHITENOISE_USE_FINDERS = True

# Documents live on local disk for now; swap to S3-compatible storage later
# by changing STORAGES["default"].
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "var" / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
