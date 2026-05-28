# Deliberate Tradeoffs — Breathe ESG Ingestion Platform

Three things I consciously chose **not** to build, with the rationale for each.

---

## 1. No Authentication or Role-Based Access Control

**What I didn't build:** A login system, user sessions, JWT tokens, or role-based permissions (e.g., `analyst` vs. `admin` vs. `read-only`).

**Why:**
The assignment's grading axes — data model quality, source handling, analyst UX, and documentation — do not reward auth infrastructure. Implementing RBAC partially and incorrectly (e.g., a `@login_required` decorator that's commented out in the submission) is worse than explicitly skipping it and documenting the gap.

**What I'd build in production:**
- `django-allauth` for authentication (email + password, optionally SSO via OAuth2 with the client's identity provider)
- Organisation-scoped roles stored in a `Membership` table: `(user, organisation, role)` where role is one of `['admin', 'analyst', 'viewer']`
- DRF's `IsAuthenticated` + a custom `IsOrgMember` permission class on all endpoints
- The `AuditLog.actor` field is already designed for this — it currently stores `"system"` but is ready to store a `User` FK

---

## 2. No File Deduplication Enforcement

**What I didn't build:** Hard rejection of duplicate file uploads based on `file_hash`. The `file_hash` field exists on both `IngestionBatch` and `RawRecord`, but re-uploading the same file is not blocked — only warned.

**Why:**
During development and evaluation, the same sample CSV is uploaded repeatedly. Blocking re-uploads would have made iterative testing require database resets between each test. Additionally, there are legitimate production scenarios for re-processing a file (e.g., after fixing a bug in the emission factor lookup table), and a hard block would require a database-level bypass to recover from.

**What I'd build in production:**
- A `DuplicateUploadPolicy` setting on `Organisation` with values `['warn', 'block', 'reprocess']`
- `'warn'` (current behaviour): accept the upload, surface a warning banner in the UI
- `'block'`: reject the upload with a 409 Conflict response and link to the existing batch
- `'reprocess'`: accept the upload but mark previous `NormalizedRecord`s for the same file as `superseded` rather than creating duplicates
- An audit log entry is written in all three cases

---

## 3. No Export or Reporting Module

**What I didn't build:** The ability to export reviewed emission data as a CSV, PDF, or structured report. There is no `/api/export/` endpoint and no "Download Report" button in the UI.

**Why:**
Export format is highly client-specific: some organisations submit to CDP (which has its own template), others to GRI, others to an internal sustainability committee that wants a branded PDF. Building a generic exporter that satisfies none of these properly is lower value than building the ingestion and review pipeline correctly. The assignment's grading criteria focus on ingestion quality, not reporting.

**What I'd build in production:**
- A `ReportTemplate` model that stores field mappings for each reporting standard (CDP, GRI, TCFD)
- A `/api/export/?org_id=1&format=csv&standard=cdp` endpoint using `django-import-export` or a custom serializer
- PDF generation via `WeasyPrint` for formatted board-level reports
- The data model already supports this — `NormalizedRecord` has all the fields needed (`scope`, `co2e_kg`, `period_start`, `period_end`, `status`) and the filter for `status='approved'` is all that's needed to get a clean export dataset
