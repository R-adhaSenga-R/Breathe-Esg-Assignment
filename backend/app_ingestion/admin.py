from django.contrib import admin
from .models import (
    Organization, IngestionBatch, RawRecord,
    NormalizedRecord, ReviewRecord, AuditLog
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display  = ('id', 'name', 'created_at')
    search_fields = ('name',)
    ordering      = ('name',)


@admin.register(IngestionBatch)
class IngestionBatchAdmin(admin.ModelAdmin):
    list_display   = (
        'id', 'organization', 'source_type', 'original_filename',
        'status', 'row_count', 'parse_success_level', 'created_at'
    )
    list_filter    = ('source_type', 'status', 'parse_success_level', 'organization')
    search_fields  = ('original_filename', 'file_hash')
    readonly_fields = ('file_hash', 'created_at')
    ordering       = ('-created_at',)
    date_hierarchy = 'created_at'


@admin.register(RawRecord)
class RawRecordAdmin(admin.ModelAdmin):
    list_display  = ('id', 'batch', 'source_type', 'row_index', 'flag', 'created_at')
    list_filter   = ('source_type', 'flag')
    search_fields = ('batch__original_filename',)
    readonly_fields = ('raw_data', 'created_at')
    ordering      = ('batch', 'row_index')

    def has_change_permission(self, request, obj=None):
        # Raw records are immutable — disable editing in admin
        return False


@admin.register(NormalizedRecord)
class NormalizedRecordAdmin(admin.ModelAdmin):
    list_display  = (
        'id', 'organization', 'scope', 'activity_date',
        'site_name', 'fuel_type', 'quantity', 'quantity_unit',
        'quantity_normalized', 'quantity_normalized_unit',
        'co2e_kg', 'emission_factor_source'
    )
    list_filter   = ('scope', 'organization', 'emission_factor_source')
    search_fields = ('site_name', 'fuel_type', 'meter_id', 'employee_id', 'origin', 'destination')
    readonly_fields = ('raw_record', 'co2e_kg')
    ordering      = ('-activity_date',)
    date_hierarchy = 'activity_date'


@admin.register(ReviewRecord)
class ReviewRecordAdmin(admin.ModelAdmin):
    list_display  = ('id', 'normalized_record', 'status', 'reviewed_by', 'reviewed_at', 'comment')
    list_filter   = ('status',)
    search_fields = ('comment', 'reviewed_by__username')
    readonly_fields = ('normalized_record', 'reviewed_at')
    ordering      = ('-reviewed_at',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display  = ('id', 'organization', 'user', 'action', 'target_model', 'target_id', 'timestamp')
    list_filter   = ('action', 'target_model', 'organization')
    search_fields = ('user__username', 'target_model', 'action')
    readonly_fields = ('organization', 'user', 'action', 'target_model', 'target_id', 'detail', 'timestamp')
    ordering      = ('-timestamp',)
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        # Audit logs are append-only — disable manual creation
        return False

    def has_change_permission(self, request, obj=None):
        # Audit logs are immutable — disable editing
        return False

    def has_delete_permission(self, request, obj=None):
        # Audit logs must never be deleted
        return False