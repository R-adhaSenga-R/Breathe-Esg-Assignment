# File: backend/breathe_esg/urls.py
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('app_ingestion.urls')),
    path('api/auth/', include('rest_framework.urls')),
]