# File: backend/app_ingestion/views.py
import os
import tempfile
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import (
    Organization, IngestionBatch, RawRecord,
    NormalizedRecord, ReviewRecord, AuditLog
)
from .serializers import (
    IngestionBatchSerializer, NormalizedRecordSerializer,
    ReviewRecordSerializer, AuditLogSerializer
)
from .parsers.universal_parser import parse_file, SuccessLevel
from .normalizer import normalize_sap_row, normalize_utility_row, normalize_travel_row


def log_action(user, org, action, model_name, target_id, detail=None):
    db_user = user if user and user.is_authenticated else None
    AuditLog.objects.create(
        user=db_user, organization=org, action=action,
        target_model=model_name, target_id=target_id,
        detail=detail or {},
    )


# ── Upload ────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_file(request):
    print("=== UPLOAD HIT ===")
    print("User:", request.user, "| Authenticated:", request.user.is_authenticated)
    print("POST data:", request.data)
    print("FILES:", request.FILES)

    uploaded = request.FILES.get('file')
    source_type = request.data.get('source_type', 'auto')
    org_id = request.data.get('org_id')

    print(f"source_type={source_type}, org_id={org_id}, file={uploaded}")

    if not uploaded:
        print("ERROR: No file in request")
        return Response({'error': 'No file provided'}, status=400)
    if source_type not in ('sap', 'utility', 'travel'):
        print("ERROR: Bad source_type:", source_type)
        return Response({'error': 'source_type must be sap, utility, or travel'}, status=400)

    try:
        org = Organization.objects.get(id=org_id)
        print("Org found:", org)
    except Organization.DoesNotExist:
        print("ERROR: Org not found for id:", org_id)
        return Response({'error': 'Organization not found'}, status=404)

    suffix = os.path.splitext(uploaded.name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    print("Temp file saved at:", tmp_path)

    try:
        parse_result = parse_file(tmp_path, filename=uploaded.name, hint=source_type)
        print("Parse result:", parse_result.success_level, "| rows:", parse_result.row_count)
    except Exception as e:
        print("ERROR during parsing:", e)
        import traceback; traceback.print_exc()
        return Response({'error': str(e)}, status=500)
    finally:
        os.unlink(tmp_path)
    
    # ... rest of the function stays the same

    # Create batch record
    batch = IngestionBatch.objects.create(
        organization      = org,
        uploaded_by       = request.user if request.user and request.user.is_authenticated else None,
        source_type       = source_type,
        original_filename = uploaded.name,
        file_hash         = parse_result.file_hash,
        file_size_bytes   = uploaded.size,
        status            = 'parsed',
        parse_success_level = parse_result.success_level.value,
        parse_errors      = parse_result.errors,
        parse_warnings    = parse_result.warnings,
        row_count         = parse_result.row_count,
    )

    log_action(request.user, org, 'upload', 'IngestionBatch', batch.id, {
        'filename': uploaded.name,
        'rows': parse_result.row_count,
        'success_level': parse_result.success_level.value,
    })

    if parse_result.success_level == SuccessLevel.FAILURE:
        batch.status = 'error'
        batch.save()
        return Response({
            'batch_id': batch.id,
            'success': False,
            'errors': parse_result.errors,
            'warnings': parse_result.warnings,
        }, status=422)

    # Save raw records
    raw_objs = [
        RawRecord(
            batch       = batch,
            row_index   = i,
            raw_data    = row,
            source_type = source_type,
            flag        = row.get('_flag', ''),
        )
        for i, row in enumerate(parse_result.data)
    ]
    RawRecord.objects.bulk_create(raw_objs, batch_size=500)

    # Normalize
    normalizer_map = {
        'sap'    : normalize_sap_row,
        'utility': normalize_utility_row,
        'travel' : normalize_travel_row,
    }
    normalize_fn = normalizer_map[source_type]

    normalized_objs = []
    for raw_obj, row in zip(raw_objs, parse_result.data):
        norm = normalize_fn(row, org, batch)
        if norm:
            norm.raw_record = raw_obj
            normalized_objs.append(norm)

    NormalizedRecord.objects.bulk_create(normalized_objs, batch_size=500)

    # Create pending review records for each normalized record
    review_objs = [
        ReviewRecord(normalized_record=n) for n in normalized_objs
    ]
    ReviewRecord.objects.bulk_create(review_objs, batch_size=500)

    batch.status = 'ready'
    batch.save()

    log_action(request.user, org, 'normalize', 'IngestionBatch', batch.id, {
        'normalized_count': len(normalized_objs),
    })

    return Response({
        'batch_id'         : batch.id,
        'success'          : True,
        'success_level'    : parse_result.success_level.value,
        'rows_parsed'      : parse_result.row_count,
        'rows_normalized'  : len(normalized_objs),
        'warnings'         : parse_result.warnings,
        'errors'           : parse_result.errors,
    }, status=201)


# ── Batches ───────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def list_batches(request):
    """GET /api/batches/?org_id=1"""
    org_id = request.query_params.get('org_id')
    qs = IngestionBatch.objects.all()
    if org_id:
        qs = qs.filter(organization_id=org_id)
    serializer = IngestionBatchSerializer(qs, many=True)
    return Response(serializer.data)


# ── Review dashboard ──────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def list_records(request):
    """
    GET /api/records/?org_id=1&scope=scope1&status=pending&batch_id=5
    Returns paginated NormalizedRecords with review status.
    """
    org_id   = request.query_params.get('org_id')
    scope    = request.query_params.get('scope')
    rv_status = request.query_params.get('status')
    batch_id = request.query_params.get('batch_id')

    qs = NormalizedRecord.objects.select_related(
        'raw_record', 'review', 'organization'
    ).all()

    if org_id:   qs = qs.filter(organization_id=org_id)
    if scope:    qs = qs.filter(scope=scope)
    if batch_id: qs = qs.filter(raw_record__batch_id=batch_id)
    if rv_status:
        qs = qs.filter(review__status=rv_status)

    paginator = PageNumberPagination()
    paginator.page_size = 50
    page = paginator.paginate_queryset(qs, request)
    serializer = NormalizedRecordSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['POST'])
@permission_classes([AllowAny])
def review_record(request, record_id):
    """
    POST /api/records/<id>/review/
    Body: { "status": "approved"|"rejected"|"flagged", "comment": "..." }
    """
    try:
        norm = NormalizedRecord.objects.get(id=record_id)
    except NormalizedRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)

    new_status = request.data.get('status')
    comment    = request.data.get('comment', '')

    if new_status not in ('approved', 'rejected', 'flagged'):
        return Response({'error': 'status must be approved, rejected, or flagged'}, status=400)

    review, _ = ReviewRecord.objects.get_or_create(normalized_record=norm)
    review.status      = new_status
    review.reviewed_by = request.user if request.user and request.user.is_authenticated else None
    review.reviewed_at = timezone.now()
    review.comment     = comment
    review.save()

    log_action(request.user, norm.organization, new_status,
               'NormalizedRecord', record_id, {'comment': comment})

    return Response({'success': True, 'status': new_status})


@api_view(['POST'])
@permission_classes([AllowAny])
def bulk_review(request):
    """
    POST /api/records/bulk-review/
    Body: { "record_ids": [1,2,3], "status": "approved", "comment": "..." }
    """
    ids        = request.data.get('record_ids', [])
    new_status = request.data.get('status')
    comment    = request.data.get('comment', '')

    if not ids or new_status not in ('approved', 'rejected', 'flagged'):
        return Response({'error': 'Provide record_ids and valid status'}, status=400)

    updated = 0
    for norm in NormalizedRecord.objects.filter(id__in=ids):
        review, _ = ReviewRecord.objects.get_or_create(normalized_record=norm)
        review.status      = new_status
        review.reviewed_by = request.user if request.user and request.user.is_authenticated else None
        review.reviewed_at = timezone.now()
        review.comment     = comment
        review.save()
        updated += 1

    return Response({'success': True, 'updated': updated})


# ── Summary stats for dashboard ───────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def dashboard_summary(request):
    """GET /api/summary/?org_id=1"""
    org_id = request.query_params.get('org_id')
    qs = NormalizedRecord.objects.all()
    if org_id:
        qs = qs.filter(organization_id=org_id)

    from django.db.models import Sum, Count
    stats = qs.aggregate(
        total_co2e   = Sum('co2e_kg'),
        scope1_co2e  = Sum('co2e_kg', filter=models.Q(scope='scope1')),
        scope2_co2e  = Sum('co2e_kg', filter=models.Q(scope='scope2')),
        scope3_co2e  = Sum('co2e_kg', filter=models.Q(scope='scope3')),
        total_records = Count('id'),
    )

    review_stats = ReviewRecord.objects.filter(
        normalized_record__organization_id=org_id
    ).values('status').annotate(count=Count('id'))

    batches_count = IngestionBatch.objects.filter(
        organization_id=org_id
    ).count()

    return Response({
        'co2e_summary'  : stats,
        'review_summary': list(review_stats),
        'batches_count' : batches_count,
    })


# Need this for dashboard_summary
from django.db import models