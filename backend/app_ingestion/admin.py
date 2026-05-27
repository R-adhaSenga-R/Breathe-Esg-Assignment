# File: backend/app_ingestion/admin.py
from django.contrib import admin
from .models import (Organization, IngestionBatch, RawRecord,
                     NormalizedRecord, ReviewRecord, AuditLog)

admin.site.register(Organization)
admin.site.register(IngestionBatch)
admin.site.register(RawRecord)
admin.site.register(NormalizedRecord)
admin.site.register(ReviewRecord)
admin.site.register(AuditLog)