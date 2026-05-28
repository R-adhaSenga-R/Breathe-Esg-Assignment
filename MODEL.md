# Data Model Design — Breathe ESG Ingestion Platform

## Overview

The data model is designed around three core requirements:
1. **Immutability of source data** — raw records must never be altered after ingestion
2. **Multi-tenancy** — each organisation's data must be strictly isolated
3. **Full audit trail** — every state change must be attributable and irreversible

---

## Entity Relationships

```
Organisation
    └── IngestionBatch (one per file upload)
            └── RawRecord        (one row per source row, never edited)
                    └── NormalizedRecord  (derived, may be flagged/corrected)
                            └── AuditLog  (append-only event log)
```

---

## Why `Organisation` as the root tenant

Every record, batch, and log entry is foreign-keyed to an `Organisation`. This enforces data isolation at the database level rather than relying on application-layer filtering, which is error-prone and audit-unfriendly. A query that accidentally omits an `org_id` filter will return no cross-tenant data because the FK constraint makes org membership structural.

---

## `RawRecord` — The Immutable Source of Truth

`RawRecord` stores the original source row verbatim in a `raw_data` JSONField, alongside:

| Field | Purpose |
|---|---|
| `source_type` | `'sap'`, `'utility'`, or `'travel'` — drives parser selection |
| `file_hash` | SHA-256 of the uploaded file — enables duplicate detection |
| `ingestion_batch` | Links back to the upload event for full provenance |
| `created_at` | Immutable timestamp set on insert |

**Critical design decision:** `RawRecord` has no `update` path. The application never calls `.save()` on an existing `RawRecord`. If source data is wrong, the correction is recorded on `NormalizedRecord.was_edited`, not by modifying the raw row. This mirrors how financial systems treat journal entries — you add a correcting entry, you do not erase the original.

---

## `NormalizedRecord` — The Working Layer

`NormalizedRecord` is the analyst-facing record. It is derived from `RawRecord` by the normalizer and holds:

| Field | Purpose |
|---|---|
| `quantity` | Original quantity as parsed from source |
| `unit` | Original unit as parsed (`'L'`, `'kWh'`, `'km'`) |
| `quantity_normalized` | Converted to a canonical unit for cross-source comparison |
| `quantity_normalized_unit` | The canonical unit (`'L'` for liquids, `'kWh'` for energy, `'km'` for travel) |
| `emission_factor` | The factor applied (kg CO₂e per unit) |
| `co2e_kg` | Computed emissions in kg CO₂e |
| `scope` | `1`, `2`, or `3` (see scope logic below) |
| `status` | `'pending'`, `'approved'`, `'flagged'`, `'rejected'` |
| `was_edited` | Boolean — set true if an analyst overrides the normalizer's output |
| `review_comment` | Free-text analyst note attached at review time |

---

## Scope 1 / 2 / 3 Categorisation Logic

| Source Type | Condition | Scope |
|---|---|---|
| SAP (fuel) | `fuel_type` in `['diesel', 'petrol', 'natural_gas']` | **1** — direct combustion owned by the organisation |
| Utility (electricity) | `utility_type == 'electricity'` | **2** — indirect, purchased energy |
| Utility (gas/heat) | `utility_type in ['gas', 'heat', 'steam']` | **1** — direct energy |
| Travel | `expense_type in ['flight', 'car', 'rail', 'taxi']` | **3** — value chain / employee activity |

The scope is assigned in `normalizer.py` at parse time and stored on `NormalizedRecord`. Analysts can override it during review (which sets `was_edited = True` and writes an `AuditLog` entry).

---

## Unit Normalisation Approach

The normalizer converts all quantities to a canonical base unit before computing emissions:

| Source Unit | Canonical Unit | Conversion |
|---|---|---|
| `ml`, `gal`, `fl oz` | `L` | standard volume conversion |
| `MWh`, `J`, `BTU` | `kWh` | standard energy conversion |
| `miles`, `m` | `km` | standard distance conversion |

This means `co2e_kg` is always computed from a consistent `quantity_normalized`, making cross-source aggregation arithmetically valid. Without this, summing a `kWh` record and an `MWh` record would produce a nonsensical total.

---

## `IngestionBatch` — Upload Provenance

Each file upload creates one `IngestionBatch` before any rows are parsed. This means:
- If the parser fails halfway through a file, the batch exists with `status='error'` and the partial rows are still queryable for debugging.
- Batches can be `locked_at` / `locked_by` once all records are approved, preventing re-review of signed-off data.
- The `file_hash` on the batch (and mirrored on each `RawRecord`) enables the application to warn when the same file is uploaded twice.

---

## `AuditLog` — Append-Only Event Log

`AuditLog` is never updated or deleted. Every write is an INSERT. Fields:

| Field | Purpose |
|---|---|
| `record` | FK to the `NormalizedRecord` that changed |
| `action` | `'approved'`, `'rejected'`, `'flagged'`, `'edited'` |
| `actor` | The user (or system) that performed the action |
| `timestamp` | UTC timestamp, set by the database (`auto_now_add`) |
| `comment` | Optional free-text note |
| `before_value` / `after_value` | JSON snapshot of changed fields |

This design satisfies auditor requirements: it is impossible to approve a record, then secretly unapprove it and pretend the approval never happened. The audit log retains the full sequence of state transitions.
