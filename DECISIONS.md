# Engineering Decisions — Breathe ESG Ingestion Platform

Every non-obvious decision made during implementation, along with the rationale and what I would clarify with the PM before a production build.

---

## Database: PostgreSQL over SQLite

**Decision:** Used PostgreSQL (via `psycopg2`) rather than Django's default SQLite.

**Rationale:**
- `JSONField` on `RawRecord.raw_data` requires PostgreSQL for indexed JSON querying. SQLite's JSON support is limited and non-indexed.
- Multi-tenancy patterns (row-level filtering on `org_id`) benefit from PostgreSQL's query planner and partial index support.
- The assignment brief mentions "auditor sign-off" and "locked batches" — these imply concurrent access, which SQLite handles poorly under write contention.

**What I'd ask the PM:** Is the deployment environment already running PostgreSQL, or do we need to provision it? If cost is a constraint, CockroachDB's free tier is a compatible alternative.

---

## Authentication: Skipped for initial build

**Decision:** All API endpoints use `AllowAny` permission class. There is no login system.

**Rationale:**
- The assignment brief focuses on data model quality and ingestion logic, not auth infrastructure. Implementing RBAC correctly takes significant time and would not be evaluated on its own grading axis.
- Adding a half-implemented auth system (e.g., tokens hardcoded in `.env`) would be worse than a clearly documented tradeoff.

**What I'd ask the PM:** Should the submission include a demo login (username/password in README), or is the evaluator expected to access the API directly? In production, I would implement auth using `django-allauth` with organisation-scoped roles (`admin`, `analyst`, `read-only`).

---

## SAP Format: CSV export over IDoc/BAPI

**Decision:** The SAP source parser reads CSV exports rather than consuming SAP IDocs or calling BAPIs directly.

**Rationale:**
- Direct SAP integration requires SAP middleware credentials, an RFC-enabled SAP system, and the `pyrfc` library — none of which are available in a take-home environment.
- In practice, most mid-size organisations export SAP data as scheduled CSV dumps to an SFTP folder. This is the most common real-world integration pattern for ESG reporting tools that are not deeply embedded in SAP.
- The parser is designed to be swappable: the `source_type` field on `RawRecord` means a future IDoc parser can write the same fields without changing the normalizer.

**What I'd ask the PM:** Does the client use SAP S/4HANA (where direct API integration via OData is feasible) or an older ECC system where CSV export is more realistic?

---

## Emission Factors: DEFRA for travel, India grid factor for electricity

**Decision:** Used UK DEFRA 2023 emission factors for travel (flight, car, rail), and the India national grid emission factor (0.82 kg CO₂e/kWh) for electricity.

**Rationale:**
- DEFRA publishes the most commonly used emission factors for corporate travel reporting and is widely accepted by auditors.
- The India grid factor is used because the assignment context is an India-based company. Using a UK or global average factor would produce materially incorrect results.
- For fuel combustion (SAP source), I used IPCC AR5 factors which are jurisdiction-neutral (the CO₂e content of diesel does not vary by country).

**What I'd ask the PM:** 
1. Does the client operate in multiple countries? If so, we need a `region` field on `NormalizedRecord` and a factor lookup table keyed on `(region, fuel_type)`.
2. Does the client want to use Scope 2 market-based vs. location-based accounting for electricity? Market-based requires contractual instruments (RECs) which we do not currently model.

---

## File Deduplication: Warning only, not blocked

**Decision:** When a file with a matching `file_hash` is uploaded, the system warns but does not reject the upload.

**Rationale:**
- During testing and development, the same sample file is uploaded many times. Blocking re-uploads would make iterative testing frustrating.
- In a real system, there are legitimate reasons to re-process a file (e.g., after fixing a bug in the normalizer). Blocking re-uploads would require a manual database bypass to recover from normalizer bugs.

**What I'd ask the PM:** Should re-upload of an identical file create a new batch (current behaviour) or should it reuse the existing batch? The audit trail implications differ significantly.

---

## Normalizer: Synchronous, not queued

**Decision:** File parsing and normalisation happens synchronously in the upload request handler, not via a task queue (Celery, etc.).

**Rationale:**
- For the file sizes involved in this assignment (hundreds of rows), synchronous processing is fast enough.
- Adding Celery requires a Redis or RabbitMQ broker, which adds infrastructure complexity with no benefit at this scale.

**What I'd ask the PM:** What is the expected file size in production? If files exceed ~10,000 rows, we should switch to async processing with a progress indicator in the UI. I would use Celery + Redis for this.

---

## Frontend: React + Vite over Django Templates

**Decision:** Built the analyst UI as a separate React SPA rather than using Django's built-in template system.

**Rationale:**
- The assignment brief mentions "analyst UX" as a graded criterion. A React SPA allows for a more interactive experience (modals, real-time status updates, drag-and-drop) that would be awkward to build in Django templates.
- The separation of frontend and backend also mirrors how production ESG platforms are built — the frontend can be updated and deployed independently of the API.

**What I'd ask the PM:** Should the frontend and backend be deployed as a single service (Django serves the React build from `STATIC_ROOT`) or as two separate services? Single-service is simpler but the two-service approach scales better.
