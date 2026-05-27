# File: backend/app_ingestion/models.py
"""
Data model for Breathe ESG ingestion pipeline.

Key design decisions:
- Organization: multi-tenancy — every record belongs to one org
- IngestionBatch: one batch per file upload — tracks source, status, who uploaded
- RawRecord: immutable copy of original row — NEVER edited after creation
- NormalizedRecord: cleaned version with emission calc — linked to raw
- ReviewRecord: analyst decision — approve/reject/flag
- AuditLog: every change to any record — required for auditor sign-off

Scope classification:
  SAP fuel     → scope1 (direct combustion)
  Electricity  → scope2 (purchased energy)
  Travel       → scope3 (value chain)
"""

from django.db import models
from django.contrib.auth.models import User


class Organization(models.Model):
    """
    One row per client company.
    Multi-tenancy: every record is scoped to an org.
    """
    name       = models.CharField(max_length=255)
    slug       = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class IngestionBatch(models.Model):
    """
    One batch = one file upload session.
    Tracks: which file, which source type, who uploaded, when, current status.
    """
    SOURCE_CHOICES = [
        ('sap',     'SAP Fuel & Procurement'),
        ('utility', 'Utility Electricity'),
        ('travel',  'Corporate Travel'),
    ]
    STATUS_CHOICES = [
        ('uploaded',    'Uploaded'),
        ('parsing',     'Parsing'),
        ('parsed',      'Parsed'),
        ('normalizing', 'Normalizing'),
        ('ready',       'Ready for Review'),
        ('reviewing',   'Under Review'),
        ('approved',    'Approved'),
        ('rejected',    'Rejected'),
        ('error',       'Error'),
    ]

    organization  = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                      related_name='batches')
    uploaded_by   = models.ForeignKey(User, on_delete=models.SET_NULL,
                                      null=True, related_name='uploads')
    source_type   = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    original_filename = models.CharField(max_length=255)
    file_hash     = models.CharField(max_length=64, blank=True)
    file_size_bytes = models.BigIntegerField(default=0)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                     default='uploaded')
    # Parser output metadata
    parse_success_level = models.CharField(max_length=20, blank=True)
    parse_errors  = models.JSONField(default=list)
    parse_warnings = models.JSONField(default=list)
    row_count     = models.IntegerField(default=0)
    # Timestamps
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
    notes         = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization} | {self.source_type} | {self.original_filename}"


class RawRecord(models.Model):
    """
    Immutable copy of one row exactly as it came from the source file.
    NEVER updated after creation. This is the source of truth.
    If an analyst wants to correct a value, that goes on NormalizedRecord.
    """
    batch        = models.ForeignKey(IngestionBatch, on_delete=models.CASCADE,
                                     related_name='raw_records')
    row_index    = models.IntegerField()         # position in original file
    raw_data     = models.JSONField()            # original row as dict
    source_type  = models.CharField(max_length=20)
    flag         = models.CharField(max_length=255, blank=True)  # _flag from parser
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['batch', 'row_index']
        unique_together = [('batch', 'row_index')]

    def __str__(self):
        return f"Raw #{self.row_index} — Batch {self.batch_id}"


class NormalizedRecord(models.Model):
    """
    Cleaned, unit-converted version of a RawRecord.
    This is what the emission calculation runs on.
    One NormalizedRecord per RawRecord (1:1).

    Scope classification:
      scope1 = SAP fuel combustion
      scope2 = grid electricity
      scope3 = business travel

    All quantities normalized to:
      Scope 1: litres (for liquid fuels), kg (for gas fuels)
      Scope 2: kWh
      Scope 3: km (for travel distance)
    """
    SCOPE_CHOICES = [
        ('scope1', 'Scope 1 — Direct'),
        ('scope2', 'Scope 2 — Electricity'),
        ('scope3', 'Scope 3 — Value Chain'),
    ]

    raw_record    = models.OneToOneField(RawRecord, on_delete=models.CASCADE,
                                         related_name='normalized')
    organization  = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                      related_name='normalized_records')
    scope         = models.CharField(max_length=10, choices=SCOPE_CHOICES)

    # Common fields across all scopes
    activity_date     = models.DateField(null=True, blank=True)
    site_name         = models.CharField(max_length=255, blank=True)
    location_city     = models.CharField(max_length=100, blank=True)
    location_state    = models.CharField(max_length=100, blank=True)

    # Scope 1 specific
    fuel_type         = models.CharField(max_length=100, blank=True)
    quantity          = models.DecimalField(max_digits=14, decimal_places=3,
                                            null=True, blank=True)
    quantity_unit     = models.CharField(max_length=20, blank=True)
    quantity_normalized = models.DecimalField(max_digits=14, decimal_places=3,
                                              null=True, blank=True)
    quantity_normalized_unit = models.CharField(max_length=20, blank=True)

    # Scope 2 specific
    consumption_kwh   = models.DecimalField(max_digits=14, decimal_places=3,
                                            null=True, blank=True)
    meter_id          = models.CharField(max_length=100, blank=True)
    discom            = models.CharField(max_length=100, blank=True)
    billing_start     = models.DateField(null=True, blank=True)
    billing_end       = models.DateField(null=True, blank=True)

    # Scope 3 specific
    travel_type       = models.CharField(max_length=50, blank=True)
    origin            = models.CharField(max_length=100, blank=True)
    destination       = models.CharField(max_length=100, blank=True)
    distance_km       = models.DecimalField(max_digits=10, decimal_places=2,
                                            null=True, blank=True)
    travel_class      = models.CharField(max_length=50, blank=True)
    employee_id       = models.CharField(max_length=50, blank=True)

    # Emission calculation
    emission_factor   = models.DecimalField(max_digits=10, decimal_places=6,
                                            null=True, blank=True)
    emission_factor_source = models.CharField(max_length=100, blank=True)
    co2e_kg           = models.DecimalField(max_digits=14, decimal_places=4,
                                            null=True, blank=True)

    # Traceability
    was_edited        = models.BooleanField(default=False)
    edit_notes        = models.TextField(blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-activity_date']

    def __str__(self):
        return f"{self.scope} | {self.site_name} | {self.co2e_kg} kgCO2e"


class ReviewRecord(models.Model):
    """
    Analyst's decision on a NormalizedRecord.
    Status flow: pending → approved / rejected / flagged
    Once approved, the NormalizedRecord is locked for audit.
    """
    STATUS_CHOICES = [
        ('pending',  'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('flagged',  'Flagged for Query'),
    ]

    normalized_record = models.OneToOneField(NormalizedRecord,
                                              on_delete=models.CASCADE,
                                              related_name='review')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                   default='pending')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL,
                                    null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    comment     = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.status} — Record {self.normalized_record_id}"


class AuditLog(models.Model):
    """
    Immutable log of every action taken in the system.
    Required for auditor sign-off.
    NEVER deleted.
    """
    ACTION_CHOICES = [
        ('upload',   'File Uploaded'),
        ('parse',    'File Parsed'),
        ('normalize','Record Normalized'),
        ('approve',  'Record Approved'),
        ('reject',   'Record Rejected'),
        ('flag',     'Record Flagged'),
        ('edit',     'Record Edited'),
        ('lock',     'Batch Locked for Audit'),
    ]

    user          = models.ForeignKey(User, on_delete=models.SET_NULL,
                                      null=True)
    organization  = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                      null=True)
    action        = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_model  = models.CharField(max_length=50)   # e.g. "IngestionBatch"
    target_id     = models.IntegerField()
    detail        = models.JSONField(default=dict)     # what changed
    timestamp     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} by {self.user} at {self.timestamp}"