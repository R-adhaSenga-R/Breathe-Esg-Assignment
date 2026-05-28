# File: backend/breathe_esg/urls.py
from django.contrib import admin
from django.urls import path, include
from app_ingestion import views
 
urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('app_ingestion.urls')),
    path('api/auth/', include('rest_framework.urls')),
     path('api/records/<int:record_id>/raw/', views.raw_record_detail, name='raw-record-detail'),
      path('api/audit-log/', views.audit_log, name='audit-log'),
]