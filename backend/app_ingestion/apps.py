# File: backend/app_ingestion/apps.py
from django.apps import AppConfig

class AppIngestionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_ingestion'