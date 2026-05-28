import os
import logging
import tempfile

from django.db import models
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from .models import (
    Organization, IngestionBatch, RawRecord,
    NormalizedRecord, ReviewRecord, AuditLog
)
from .serializers import (
    IngestionBatchSerializer, NormalizedRecordSerializer,
    ReviewRecordSerializer, AuditLogSerializer, RawRecordSerializer
)
from .parsers.universal_parser import parse_file, SuccessLevel
from .normalizer import normalize_sap_row, normalize_utility_row, normalize_travel_row

logger = logging.getLogger(__name__)


def log_action(user, org, action, model_name, target_id, detail=None):
    db_user = user if user and user.is_authenticated else None
    AuditLog.objects.create(
        user=db_user, organization=org, action=action,
        target_model=model_name, target_id=target_id,
        detail=detail or {},
    )


# ── Upload ─────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def upload_file(request):
    """POST /api/upload/"""
    logger.info("Upload request received | user=%s", request.user)

    uploaded    = request.FILES.get('file')
    source_type = request.data.get('source_type', 'auto')
    org_id      = request.data.get('org_id')

    if not uploaded:
        logger.warning("Upload rejected: no file in request")
        return Response({'error': 'No file provided'}, status=400)
    if source_type not in ('sap', 'utility', 'travel'):
        logger.warning("Upload rejected: bad source_type=%s", source_type)
        return Response({'error': 'source_type must be sap, utility, or travel'}, status=400)

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning("Upload rejected: org not found id=%s", org_id)
        return Response({'error': 'Organization not found'}, status=404)

    # Warn if same file hash already uploaded
    suffix = os.path.splitext(uploaded.name)[1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        for chunk in uploaded.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        parse_result = parse_file(tmp_path, filename=uploaded.name, hint=source_type)
        logger.info("Parsed file: success_level=%s rows=%s", parse_result.success_level, parse_result.row_count)
    except Exception as exc:
        logger.exception("Parse failure for file=%s", uploaded.name)
        return Response({'error': str(exc)}, status=500)
    finally:
        os.unlink(tmp_path)

    # Duplicate-file warning (non-blocking)
    duplicate_warning = None
    if IngestionBatch.objects.filter(file_hash=parse_result.file_hash, organization=org).exists():
        duplicate_warning = f"File '{uploaded.name}' has been uploaded before (same content). A new batch has been created."
        logger.warning("Duplicate file upload: hash=%s org=%s", parse_result.file_hash, org_id)

    batch = IngestionBatch.objects.create(
        organization        = org,
        uploaded_by         = request.user if request.user and request.user.is_authenticated else None,
        source_type         = source_type,
        original_filename   = uploaded.name,
        file_hash           = parse_result.file_hash,
        file_size_bytes     = uploaded.size,
        status              = 'parsed',
        parse_success_level = parse_result.success_level.value,
        parse_errors        = parse_result.errors,
        parse_warnings      = parse_result.warnings,
        row_count           = parse_result.row_count,
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

    review_objs = [ReviewRecord(normalized_record=n) for n in normalized_objs]
    ReviewRecord.objects.bulk_create(review_objs, batch_size=500)

    batch.status = 'ready'
    batch.save()

    log_action(request.user, org, 'normalize', 'IngestionBatch', batch.id, {
        'normalized_count': len(normalized_objs),
    })

    response_data = {
        'batch_id'        : batch.id,
        'success'         : True,
        'success_level'   : parse_result.success_level.value,
        'rows_parsed'     : parse_result.row_count,
        'rows_normalized' : len(normalized_objs),
        'warnings'        : parse_result.warnings,
        'errors'          : parse_result.errors,
    }
    if duplicate_warning:
        response_data['duplicate_warning'] = duplicate_warning

    return Response(response_data, status=201)


# ── Batches ────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def list_batches(request):
    """GET /api/batches/?org_id=1"""
    org_id = request.query_params.get('org_id')
    qs = IngestionBatch.objects.all().order_by('-created_at')
    if org_id:
        qs = qs.filter(organization_id=org_id)
    serializer = IngestionBatchSerializer(qs, many=True)
    return Response(serializer.data)


# ── Review dashboard ───────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def list_records(request):
    """
    GET /api/records/?org_id=1&scope=scope1&status=pending&batch_id=5
    Returns paginated NormalizedRecords with review status.
    """
    org_id    = request.query_params.get('org_id')
    scope     = request.query_params.get('scope')
    rv_status = request.query_params.get('status')
    batch_id  = request.query_params.get('batch_id')

    qs = NormalizedRecord.objects.select_related(
        'raw_record', 'review', 'organization'
    ).all().order_by('-id')

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


@api_view(['GET'])
@permission_classes([AllowAny])
def raw_record_detail(request, record_id):
    """
    GET /api/records/<id>/raw/
    Returns the original unparsed source row for a NormalizedRecord.
    Enables drill-down in the analyst UI.
    """
    try:
        norm = NormalizedRecord.objects.select_related('raw_record').get(id=record_id)
    except NormalizedRecord.DoesNotExist:
        return Response({'error': 'Record not found'}, status=404)

    raw = norm.raw_record
    if not raw:
        return Response({'error': 'No raw record linked'}, status=404)

    return Response({
        'normalized_id' : record_id,
        'raw_id'        : raw.id,
        'row_index'     : raw.row_index,
        'source_type'   : raw.source_type,
        'flag'          : raw.flag,
        'raw_data'      : raw.raw_data,     # The original source JSON
        'ingested_at'   : raw.created_at,
    })


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
    old_status           = review.status
    review.status        = new_status
    review.reviewed_by   = request.user if request.user and request.user.is_authenticated else None
    review.reviewed_at   = timezone.now()
    review.comment       = comment
    review.save()

    log_action(request.user, norm.organization, new_status,
               'NormalizedRecord', record_id,
               {'comment': comment, 'previous_status': old_status})

    logger.info("Record %s reviewed: %s → %s", record_id, old_status, new_status)
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
    for norm in NormalizedRecord.objects.filter(id__in=ids).select_related('organization'):
        review, _          = ReviewRecord.objects.get_or_create(normalized_record=norm)
        review.status      = new_status
        review.reviewed_by = request.user if request.user and request.user.is_authenticated else None
        review.reviewed_at = timezone.now()
        review.comment     = comment
        review.save()
        updated += 1

    logger.info("Bulk review: %s records → %s", updated, new_status)
    return Response({'success': True, 'updated': updated})


# ── Summary stats ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def dashboard_summary(request):
    """GET /api/summary/?org_id=1"""
    from django.db.models import Sum, Count

    org_id = request.query_params.get('org_id')
    qs = NormalizedRecord.objects.all()
    if org_id:
        qs = qs.filter(organization_id=org_id)

    stats = qs.aggregate(
        total_co2e    = Sum('co2e_kg'),
        scope1_co2e   = Sum('co2e_kg', filter=models.Q(scope='scope1')),
        scope2_co2e   = Sum('co2e_kg', filter=models.Q(scope='scope2')),
        scope3_co2e   = Sum('co2e_kg', filter=models.Q(scope='scope3')),
        total_records = Count('id'),
    )

    review_stats = ReviewRecord.objects.filter(
        normalized_record__organization_id=org_id
    ).values('status').annotate(count=Count('id'))

    batches_count = IngestionBatch.objects.filter(organization_id=org_id).count()

    return Response({
        'co2e_summary'  : stats,
        'review_summary': list(review_stats),
        'batches_count' : batches_count,
    })


# ── Audit log ──────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def audit_log(request):
    """
    GET /api/audit-log/?org_id=1&page=1
    Returns paginated audit trail for an organisation.
    """
    org_id = request.query_params.get('org_id')
    qs = AuditLog.objects.all().order_by('-timestamp')
    if org_id:
        qs = qs.filter(organization_id=org_id)

    paginator = PageNumberPagination()
    paginator.page_size = 100
    page = paginator.paginate_queryset(qs, request)
    serializer = AuditLogSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)