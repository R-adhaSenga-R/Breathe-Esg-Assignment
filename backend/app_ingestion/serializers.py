# File: backend/app_ingestion/serializers.py
from rest_framework import serializers
from .models import (
    Organization, IngestionBatch, RawRecord,
    NormalizedRecord, ReviewRecord, AuditLog
)


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Organization
        fields = ['id', 'name', 'slug', 'created_at']


class IngestionBatchSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    organization_name = serializers.SerializerMethodField()

    class Meta:
        model  = IngestionBatch
        fields = [
            'id', 'organization', 'organization_name',
            'uploaded_by', 'uploaded_by_name', 'source_type',
            'original_filename', 'file_hash', 'file_size_bytes',
            'status', 'parse_success_level', 'parse_errors',
            'parse_warnings', 'row_count', 'created_at', 'notes',
        ]

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.get_full_name() if obj.uploaded_by else None

    def get_organization_name(self, obj):
        return obj.organization.name


class RawRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model  = RawRecord
        fields = ['id', 'batch', 'row_index', 'raw_data',
                  'source_type', 'flag', 'created_at']


class NormalizedRecordSerializer(serializers.ModelSerializer):
    review_status = serializers.SerializerMethodField()

    class Meta:
        model  = NormalizedRecord
        fields = [
            'id', 'raw_record', 'organization', 'scope',
            'activity_date', 'site_name', 'location_city', 'location_state',
            'fuel_type', 'quantity', 'quantity_unit',
            'consumption_kwh', 'meter_id', 'discom',
            'billing_start', 'billing_end',
            'travel_type', 'origin', 'destination',
            'distance_km', 'travel_class', 'employee_id',
            'emission_factor', 'emission_factor_source', 'co2e_kg',
            'was_edited', 'edit_notes',
            'created_at', 'updated_at', 'review_status',
        ]

    def get_review_status(self, obj):
        try:
            return obj.review.status
        except ReviewRecord.DoesNotExist:
            return 'pending'


class ReviewRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ReviewRecord
        fields = ['id', 'normalized_record', 'status',
                  'reviewed_by', 'reviewed_at', 'comment', 'created_at']
        read_only_fields = ['reviewed_by', 'reviewed_at']


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = AuditLog
        fields = ['id', 'user', 'organization', 'action',
                  'target_model', 'target_id', 'detail', 'timestamp']