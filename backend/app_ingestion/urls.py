# File: backend/app_ingestion/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('upload/',                   views.upload_file,      name='upload'),
    path('batches/',                  views.list_batches,     name='batches'),
    path('records/',                  views.list_records,     name='records'),
    path('records/<int:record_id>/review/', views.review_record, name='review'),
    path('records/bulk-review/',      views.bulk_review,      name='bulk-review'),
    path('summary/',                  views.dashboard_summary, name='summary'),
]