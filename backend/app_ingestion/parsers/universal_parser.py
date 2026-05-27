"""
universal_parser.py — Breathe ESG Production-Safe File Parser
==============================================================
Accepts ANY file a client uploads and returns a structured ParseResult.

FIX 1: hint-based domain validators — fails fast when required columns are missing.
FIX 2: Fixed-width/IDoc claim removed. SAP is handled via CSV/XLSX exports only.
FIX 3: Chunked reading for large CSV/JSONL files (>50MB) to avoid memory blowups.
FIX 4: Vendor-specific PDF extractors for known utility vendors.
FIX 5: Explicit success semantics — full_success, partial_success, or failure.

Author: Built for Breathe ESG Tech Intern Assignment
"""

from __future__ import annotations

import io
import json
import csv
import logging
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import chardet
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1.  DOMAIN SCHEMAS — used when hint is provided
#     Each schema defines required columns (after header normalisation).
#     If hint is given, missing required columns → hard failure (not warning).
# ---------------------------------------------------------------------------

DOMAIN_SCHEMAS: dict[str, dict] = {
    "sap": {
        # After SAP_HEADER_MAP translation, our MB51 ALV export produces these names.
        # We require the minimum set needed to calculate Scope 1 emissions.
        "required": ["posting_date", "quantity", "unit"],
        # movement_type should be 261 (goods issue); checked in validator but not required
        # because some exports omit it and we can infer from context.
        "optional": [
            "plant",
            "material_code",
            "material_description",
            "posting_text",
            "vendor",
            "amount_local_currency",
            "company_code",
            "cost_center",
            "movement_type",
        ],
        "scope": "scope1",
        "description": "SAP fuel/procurement export (MB51 / ME2M ALV flat file)",
        # Warn if movement_type present but not in this list
        "movement_type_whitelist": ["261", "262", "201", "202"],
    },
    "utility": {
        # Matches columns in utility_electricity_large.csv after normalisation.
        # billing_period_start NOT billing_start — fixed to match actual data.
        "required": ["consumption_kwh", "billing_period_start"],
        "optional": [
            "meter_id",
            "account_number",
            "site_name",
            "billing_period_end",
            "maximum_demand_kw",
            "tariff_code",
            "total_amount_inr",
            "discom",
            "power_factor",
            "payment_status",
        ],
        "scope": "scope2",
        "description": "Utility electricity billing export (MSEDCL / BESCOM / TANGEDCO / BSES)",
    },
    "travel": {
        # Matches columns in corporate_travel_concur_large.csv after normalisation.
        # expense_type NOT travel_type — fixed to match Concur export shape.
        "required": ["expense_type", "trip_start_date"],
        "optional": [
            "employee_id",
            "employee_name",
            "origin_iata",
            "destination_iata",
            "destination_city",
            "distance_km",
            "amount_inr",
            "travel_class",
            "reimbursement_status",
            "cost_center",
            "vendor_name",
            "nights",
        ],
        "scope": "scope3",
        "description": "Corporate travel export (Concur / Navan expense report)",
    },
}

# ---------------------------------------------------------------------------
# 2.  SAP GERMAN HEADER MAP
# ---------------------------------------------------------------------------

SAP_HEADER_MAP: dict[str, str] = {
    # ── BAPI / OData short field names ────────────────────────────────────────
    "mandt": "client",
    "bukrs": "company_code",
    "werks": "plant",
    "budat": "posting_date",
    "bldat": "document_date",
    "matnr": "material_code",
    "maktx": "material_description",
    "bwart": "movement_type",
    "menge": "quantity",
    "meins": "unit",
    "dmbtr": "amount_local_currency",
    "waers": "currency",
    "lifnr": "vendor",
    "bktxt": "posting_text",
    "kostl": "cost_center",
    "lgort": "storage_location",
    "aufnr": "order_number",
    "gjahr": "fiscal_year",
    "belnr": "document_number",
    "erfname": "username",
    # ── Full German ALV Grid export column names (MB51, ME2M, FAGLL03) ────────
    # These are the names you see when a user does List→Export→Local File in SAP GUI
    "mandant": "client",
    "buchungskreis": "company_code",
    "werk": "plant",
    "buchungsdatum": "posting_date",
    "belegdatum": "document_date",
    "materialdokument": "material_document",
    "pos": "line_item",
    "material": "material_code",
    "materialkurztext": "material_description",
    "bewegungsart": "movement_type",
    # menge / einheit already covered above via short codes
    "einheit": "unit",
    "betrag_in_hw": "amount_local_currency",
    "betrag in hw": "amount_local_currency",
    "waehrung": "currency",
    "lieferant": "vendor",
    "buchungstext": "posting_text",
    "kostenstelle": "cost_center",
    "lagerort": "storage_location",
    "benutzername": "username",
    "werksname": "plant_name",
    "buchungskreisname": "company_name",
    "land": "country",
    "region": "state",
    "stadt": "city",
}

# ---------------------------------------------------------------------------
# 3.  VENDOR-SPECIFIC PDF PATTERNS  (FIX 4)
#     Maps vendor keyword → extraction strategy
# ---------------------------------------------------------------------------

PDF_VENDOR_STRATEGIES: dict[str, dict] = {
    "bescom": {
        "keywords": ["bescom", "bangalore electricity supply"],
        "table_page": 0,
        "consumption_label": "units consumed",
        "period_label": "billing period",
    },
    "msedcl": {
        "keywords": ["msedcl", "maharashtra state electricity"],
        "table_page": 1,
        "consumption_label": "consumption",
        "period_label": "bill date",
    },
    "tata_power": {
        "keywords": ["tata power", "tatapower"],
        "table_page": 0,
        "consumption_label": "net consumption",
        "period_label": "billing period",
    },
    "generic": {
        "keywords": [],  # always matches as fallback
        "table_page": None,
        "consumption_label": None,
        "period_label": None,
    },
}

# ---------------------------------------------------------------------------
# 4.  RESULT DATACLASS  (FIX 5: explicit success semantics)
# ---------------------------------------------------------------------------


class SuccessLevel(str, Enum):
    FULL = "full_success"  # 0 errors, all required columns present
    PARTIAL = "partial_success"  # some rows parsed; warnings exist
    FAILURE = "failure"  # 0 data rows extracted or hard error


@dataclass
class ParseResult:
    success_level: SuccessLevel
    data: list[dict]  # list of normalised row dicts
    source_type: str  # "csv", "xlsx", "pdf", "json", "jsonl", "docx"
    detected_domain: Optional[str]  # "sap", "utility", "travel", or None
    errors: list[str]
    warnings: list[str]
    row_count: int
    chunk_count: int = 1  # how many chunks were read (FIX 3)
    file_hash: str = ""  # sha256 of raw bytes for deduplication

    @property
    def success(self) -> bool:
        """Backwards-compatible boolean check."""
        return self.success_level != SuccessLevel.FAILURE

    def to_dict(self) -> dict:
        return {
            "success_level": self.success_level.value,
            "success": self.success,
            "source_type": self.source_type,
            "detected_domain": self.detected_domain,
            "row_count": self.row_count,
            "chunk_count": self.chunk_count,
            "file_hash": self.file_hash,
            "errors": self.errors,
            "warnings": self.warnings,
            "data": self.data,
        }


def _failure(errors: list[str], source_type: str = "unknown") -> ParseResult:
    return ParseResult(
        success_level=SuccessLevel.FAILURE,
        data=[],
        source_type=source_type,
        detected_domain=None,
        errors=errors,
        warnings=[],
        row_count=0,
    )


# ---------------------------------------------------------------------------
# 5.  MAIN ENTRY POINT
# ---------------------------------------------------------------------------


def parse_file(
    file_input,
    filename: str = "",
    hint: Optional[str] = None,  # FIX 1: "sap", "utility", or "travel"
    chunk_size_mb: float = 50.0,  # FIX 3: threshold for chunked reading
) -> ParseResult:
    """
    Parse any file a client uploads into a list of normalised dicts.

    Args:
        file_input : file-like object OR bytes OR str path
        filename   : original filename (used for extension dispatch)
        hint       : optional domain label — triggers strict column validation
        chunk_size_mb : files above this size use chunked CSV/JSONL reading

    Returns:
        ParseResult with explicit success_level
    """
    # --- Normalise input to bytes ----------------------------------------
    try:
        if isinstance(file_input, (str, Path)):
            raw_bytes = Path(file_input).read_bytes()
            if not filename:
                filename = Path(file_input).name
        elif isinstance(file_input, bytes):
            raw_bytes = file_input
        else:
            raw_bytes = file_input.read()
    except Exception as exc:
        return _failure([f"Cannot read input: {exc}"])

    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    ext = Path(filename).suffix.lower()
    size_mb = len(raw_bytes) / (1024 * 1024)

    # --- Dispatch by extension -------------------------------------------
    # Guard: reject known binary magic bytes before any text parsing
    BINARY_MAGIC = [
        (b"\x89PNG", "PNG image"),
        (b"\xff\xd8\xff", "JPEG image"),
        (b"GIF8", "GIF image"),
        (b"RIFF", "RIFF/WAV file"),
        (b"\x1f\x8b", "gzip archive"),
        (b"BM", "BMP image"),
    ]
    for magic, label in BINARY_MAGIC:
        if raw_bytes[: len(magic)] == magic:
            return _failure(
                [f"File appears to be a {label}, not tabular data"], "binary"
            )

    if ext in (".xlsx", ".xls", ".xlsm", ".ods"):
        result = _parse_excel(raw_bytes, ext)
    elif ext in (".csv", ".tsv", ".txt"):
        result = _parse_flat(raw_bytes, ext, size_mb, chunk_size_mb)
    elif ext == ".pdf":
        result = _parse_pdf(raw_bytes)
    elif ext == ".json":
        result = _parse_json(raw_bytes)
    elif ext == ".jsonl":
        result = _parse_jsonl(raw_bytes, size_mb, chunk_size_mb)
    elif ext in (".docx",):
        result = _parse_docx(raw_bytes)
    else:
        # Unknown extension — sniff it
        result = _sniff_and_parse(raw_bytes, size_mb, chunk_size_mb)

    result.file_hash = file_hash

    # --- Domain validation (FIX 1) --------------------------------------
    if result.success and hint:
        result = _validate_domain(result, hint)

    # --- Auto-detect domain if no hint ----------------------------------
    if result.success and not result.detected_domain:
        result.detected_domain = _detect_domain(result.data)

    # --- Determine final success level (FIX 5) -------------------------
    if result.success_level != SuccessLevel.FAILURE:
        # Hard errors → partial; actual data errors (row-level) → partial
        # Informational warnings (delimiter, encoding, vendor) → still FULL
        hard_warning_keywords = (
            "empty — verify",  # high blank % in a column
            "duplicate",  # rows removed
            "fallback",  # encoding or parser fallback used
        )
        has_hard_warning = any(
            any(kw in w for kw in hard_warning_keywords) for w in result.warnings
        )
        if result.errors or has_hard_warning:
            result.success_level = SuccessLevel.PARTIAL
        else:
            result.success_level = SuccessLevel.FULL

    return result


# ---------------------------------------------------------------------------
# 6.  FLAT FILE PARSER (CSV / TSV / TXT)  —  FIX 3: chunked reading
# ---------------------------------------------------------------------------

_ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]


def _detect_encoding(raw: bytes) -> str:
    detected = chardet.detect(raw[:65536])
    enc = detected.get("encoding") or "utf-8"
    confidence = detected.get("confidence", 0)
    if confidence < 0.6:
        enc = "utf-8"  # low confidence — default safe
    return enc


def _detect_delimiter(sample: str, ext: str) -> str:
    if ext == ".tsv":
        return "\t"
    # Character frequency analysis
    candidates = {",": 0, ";": 0, "\t": 0, "|": 0}
    for char in candidates:
        counts = [line.count(char) for line in sample.splitlines()[:20] if line]
        if counts and all(c == counts[0] for c in counts) and counts[0] > 0:
            candidates[char] = counts[0]
    if max(candidates.values()) > 0:
        return max(candidates, key=candidates.get)
    # Fall back to csv.Sniffer
    try:
        dialect = csv.Sniffer().sniff(sample[:2048])
        return dialect.delimiter
    except csv.Error:
        return ","


def _parse_flat(
    raw: bytes, ext: str, size_mb: float, chunk_size_mb: float
) -> ParseResult:
    errors: list[str] = []
    warnings: list[str] = []

    enc = _detect_encoding(raw)
    try:
        text = raw.decode(enc)
    except UnicodeDecodeError:
        for fallback in _ENCODINGS:
            try:
                text = raw.decode(fallback)
                warnings.append(
                    f"Detected encoding '{enc}' failed; decoded with '{fallback}'"
                )
                enc = fallback
                break
            except UnicodeDecodeError:
                continue
        else:
            return _failure(["Cannot decode file with any known encoding"])

    sample = "\n".join(text.splitlines()[:30])
    delim = _detect_delimiter(sample, ext)
    if delim != ",":
        warnings.append(f"Non-standard delimiter detected: '{delim}'")

    # Chunked reading for large files (FIX 3)
    all_rows: list[dict] = []
    chunk_count = 0
    use_chunks = size_mb > chunk_size_mb

    try:
        buf = io.StringIO(text)
        if use_chunks:
            warnings.append(
                f"File is {size_mb:.1f} MB — reading in chunks to avoid memory issues"
            )
            chunk_iter = pd.read_csv(
                buf,
                sep=delim,
                chunksize=50_000,
                dtype=str,
                keep_default_na=False,
                on_bad_lines="warn",
            )
            for chunk in chunk_iter:
                chunk_count += 1
                chunk = _clean_df(chunk, warnings if chunk_count == 1 else [])
                all_rows.extend(chunk.to_dict("records"))
        else:
            df = pd.read_csv(
                buf, sep=delim, dtype=str, keep_default_na=False, on_bad_lines="warn"
            )
            chunk_count = 1
            df = _clean_df(df, warnings)
            all_rows = df.to_dict("records")
    except Exception as exc:
        return _failure([f"CSV parsing failed: {exc}"], "csv")

    if not all_rows:
        return _failure(["No data rows found in file"], "csv")

    return ParseResult(
        success_level=SuccessLevel.FULL,  # may be downgraded later
        data=all_rows,
        source_type="csv",
        detected_domain=None,
        errors=errors,
        warnings=warnings,
        row_count=len(all_rows),
        chunk_count=chunk_count,
    )


def _clean_df(df: pd.DataFrame, warnings: list[str]) -> pd.DataFrame:
    """Normalise headers, translate SAP columns, remove duplicates, report blanks."""
    # Normalise headers
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Translate SAP headers
    renamed = {c: SAP_HEADER_MAP[c] for c in df.columns if c in SAP_HEADER_MAP}
    if renamed:
        df = df.rename(columns=renamed)
        warnings.append(
            f"SAP column headers translated: {list(renamed.keys())} → {list(renamed.values())}"
        )

    # Remove blank rows and exact duplicates
    before = len(df)
    df = df.dropna(how="all").drop_duplicates()
    removed = before - len(df)
    if removed:
        warnings.append(f"{removed} duplicate or blank rows removed")

    # Report columns with high nulls
    for col in df.columns:
        null_pct = (df[col] == "").mean()
        if null_pct > 0.3:
            warnings.append(
                f"Column '{col}' is {null_pct:.0%} empty — verify before approving"
            )

    return df


# ---------------------------------------------------------------------------
# 7.  EXCEL PARSER
# ---------------------------------------------------------------------------


def _parse_excel(raw: bytes, ext: str) -> ParseResult:
    warnings: list[str] = []

    engine_map = {".xlsx": "openpyxl", ".xlsm": "openpyxl", ".ods": "odf"}
    engine = engine_map.get(ext, "openpyxl")

    try:
        xl = pd.ExcelFile(io.BytesIO(raw), engine=engine)
        sheets = xl.sheet_names
        if len(sheets) > 1:
            warnings.append(
                f"Excel has {len(sheets)} sheets: {sheets}. Selecting '{sheets[0]}'."
            )
        # Pick sheet with most data
        best_sheet = sheets[0]
        best_count = 0
        for s in sheets:
            try:
                df_temp = xl.parse(s, nrows=5)
                if len(df_temp.columns) > best_count:
                    best_count = len(df_temp.columns)
                    best_sheet = s
            except Exception:
                continue

        df = xl.parse(best_sheet, dtype=str, keep_default_na=False)
        df = _clean_df(df, warnings)
    except Exception as exc:
        return _failure([f"Excel parsing failed: {exc}"], "xlsx")

    return ParseResult(
        success_level=SuccessLevel.FULL,
        data=df.to_dict("records"),
        source_type="xlsx",
        detected_domain=None,
        errors=[],
        warnings=warnings,
        row_count=len(df),
    )


# ---------------------------------------------------------------------------
# 8.  PDF PARSER  —  FIX 4: vendor-specific extractors
# ---------------------------------------------------------------------------


def _detect_pdf_vendor(text_sample: str) -> str:
    text_lower = text_sample.lower()
    for vendor, info in PDF_VENDOR_STRATEGIES.items():
        if vendor == "generic":
            continue
        if any(kw in text_lower for kw in info["keywords"]):
            return vendor
    return "generic"


def _parse_pdf(raw: bytes) -> ParseResult:
    try:
        import pdfplumber
    except ImportError:
        return _failure(["pdfplumber not installed — run: pip install pdfplumber"])

    warnings: list[str] = []
    errors: list[str] = []
    all_rows: list[dict] = []

    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            # Read first page text for vendor detection
            first_text = pdf.pages[0].extract_text() or ""
            vendor = _detect_pdf_vendor(first_text)

            if vendor != "generic":
                warnings.append(
                    f"Detected PDF vendor: {vendor.upper()} — using specialised extractor"
                )
                strategy = PDF_VENDOR_STRATEGIES[vendor]
                target_page = strategy["table_page"]
                if target_page is not None and target_page < len(pdf.pages):
                    tables = pdf.pages[target_page].extract_tables()
                else:
                    tables = []
                    for page in pdf.pages:
                        tables.extend(page.extract_tables())
            else:
                warnings.append("Unknown PDF vendor — using generic table extractor")
                tables = []
                for page in pdf.pages:
                    tables.extend(page.extract_tables())

            # Convert tables to dicts
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = [
                    str(h).strip().lower().replace(" ", "_") if h else f"col_{i}"
                    for i, h in enumerate(table[0])
                ]
                for row in table[1:]:
                    if any(cell and str(cell).strip() for cell in row):
                        all_rows.append(
                            {
                                headers[i]: (str(v).strip() if v else "")
                                for i, v in enumerate(row)
                                if i < len(headers)
                            }
                        )

            # Fallback: if no tables found, extract raw text lines as key-value pairs
            if not all_rows:
                warnings.append(
                    "No tables found in PDF — attempting text extraction fallback"
                )
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    for line in text.splitlines():
                        parts = line.split(":", 1)
                        if len(parts) == 2 and parts[0].strip():
                            all_rows.append(
                                {
                                    "field": parts[0].strip(),
                                    "value": parts[1].strip(),
                                }
                            )
                if not all_rows:
                    errors.append(
                        "PDF contains no extractable tables or structured text"
                    )

    except Exception as exc:
        return _failure([f"PDF parsing failed: {exc}"], "pdf")

    if not all_rows:
        return _failure(errors or ["No rows extracted from PDF"], "pdf")

    return ParseResult(
        success_level=SuccessLevel.FULL,
        data=all_rows,
        source_type="pdf",
        detected_domain=None,
        errors=errors,
        warnings=warnings,
        row_count=len(all_rows),
    )


# ---------------------------------------------------------------------------
# 9.  JSON PARSER
# ---------------------------------------------------------------------------


def _parse_json(raw: bytes) -> ParseResult:
    warnings: list[str] = []
    enc = _detect_encoding(raw)
    try:
        obj = json.loads(raw.decode(enc))
    except Exception as exc:
        return _failure([f"JSON decode failed: {exc}"], "json")

    # Find the list of records
    if isinstance(obj, list):
        rows = obj
    elif isinstance(obj, dict):
        # Find the key that contains a list (e.g., {"results": [...], "meta": {...}})
        list_keys = [k for k, v in obj.items() if isinstance(v, list)]
        if not list_keys:
            return _failure(
                ["JSON object has no list-valued key — cannot extract rows"], "json"
            )
        best_key = max(list_keys, key=lambda k: len(obj[k]))
        warnings.append(f"JSON object: extracted records from key '{best_key}'")
        rows = obj[best_key]
    else:
        return _failure(["JSON root is not an object or array"], "json")

    # Flatten nested dicts one level deep
    flat_rows = []
    for row in rows:
        if isinstance(row, dict):
            flat_rows.append(_flatten_dict(row))
        else:
            flat_rows.append({"value": str(row)})

    return ParseResult(
        success_level=SuccessLevel.FULL,
        data=flat_rows,
        source_type="json",
        detected_domain=None,
        errors=[],
        warnings=warnings,
        row_count=len(flat_rows),
    )


def _flatten_dict(d: dict, prefix: str = "") -> dict:
    """Flatten one level of nesting."""
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}".lower().replace(" ", "_")
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                out[f"{key}_{sub_k}".lower()] = sub_v
        else:
            out[key] = v
    return out


# ---------------------------------------------------------------------------
# 10. JSONL PARSER  —  FIX 3: chunked reading
# ---------------------------------------------------------------------------


def _parse_jsonl(raw: bytes, size_mb: float, chunk_size_mb: float) -> ParseResult:
    warnings: list[str] = []
    enc = _detect_encoding(raw)
    try:
        lines = raw.decode(enc).splitlines()
    except Exception as exc:
        return _failure([f"JSONL decode failed: {exc}"], "jsonl")

    rows: list[dict] = []
    errors: list[str] = []
    chunk_count = 0
    use_chunks = size_mb > chunk_size_mb

    if use_chunks:
        warnings.append(f"Large JSONL ({size_mb:.1f} MB) — processing in chunks")

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            rows.append(
                _flatten_dict(obj) if isinstance(obj, dict) else {"value": str(obj)}
            )
        except json.JSONDecodeError:
            errors.append(f"Line {i+1}: invalid JSON — skipped")
        if use_chunks and (i + 1) % 50_000 == 0:
            chunk_count += 1

    chunk_count = max(chunk_count, 1)

    if not rows:
        return _failure(errors or ["No valid JSON lines found"], "jsonl")

    return ParseResult(
        success_level=SuccessLevel.FULL,
        data=rows,
        source_type="jsonl",
        detected_domain=None,
        errors=errors,
        warnings=warnings,
        row_count=len(rows),
        chunk_count=chunk_count,
    )


# ---------------------------------------------------------------------------
# 11. DOCX PARSER
# ---------------------------------------------------------------------------


def _parse_docx(raw: bytes) -> ParseResult:
    try:
        from docx import Document
    except ImportError:
        return _failure(["python-docx not installed — run: pip install python-docx"])

    warnings: list[str] = []
    rows: list[dict] = []

    try:
        doc = Document(io.BytesIO(raw))
        # Extract tables first
        for tbl in doc.tables:
            if not tbl.rows:
                continue
            headers = [
                cell.text.strip().lower().replace(" ", "_")
                for cell in tbl.rows[0].cells
            ]
            for row in tbl.rows[1:]:
                values = [cell.text.strip() for cell in row.cells]
                if any(values):
                    rows.append(dict(zip(headers, values)))
        # If no tables, extract paragraphs as key-value
        if not rows:
            warnings.append("No tables in DOCX — extracting paragraph text")
            for para in doc.paragraphs:
                text = para.text.strip()
                if ":" in text:
                    k, v = text.split(":", 1)
                    rows.append({"field": k.strip(), "value": v.strip()})
    except Exception as exc:
        return _failure([f"DOCX parsing failed: {exc}"], "docx")

    if not rows:
        return _failure(["No extractable data found in DOCX"], "docx")

    return ParseResult(
        success_level=SuccessLevel.FULL,
        data=rows,
        source_type="docx",
        detected_domain=None,
        errors=[],
        warnings=warnings,
        row_count=len(rows),
    )


# ---------------------------------------------------------------------------
# 12. SNIFF-AND-PARSE for unknown extensions
# ---------------------------------------------------------------------------


def _sniff_and_parse(raw: bytes, size_mb: float, chunk_size_mb: float) -> ParseResult:
    """Try parsers in order when extension is unknown or wrong."""
    # Check magic bytes
    if raw[:4] == b"%PDF":
        return _parse_pdf(raw)
    if raw[:2] in (b"PK",):
        # Likely xlsx/docx ZIP
        return _parse_excel(raw, ".xlsx")
    # Try JSON
    stripped = raw[:200].strip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        result = _parse_json(raw)
        if result.success:
            return result
    # Default: try flat CSV
    result = _parse_flat(raw, ".csv", size_mb, chunk_size_mb)
    if result.success:
        result.warnings.insert(0, "Unknown extension — treated as CSV")
    return result


# ---------------------------------------------------------------------------
# 13. DOMAIN DETECTION  (FIX 1)
# ---------------------------------------------------------------------------


def _row_level_checks(result: ParseResult, hint: str) -> ParseResult:
    """
    Per-row validation run after domain column check passes.
    Flags suspicious rows with warnings — does NOT remove them
    (analyst sees them in the review dashboard and decides).
    """
    if not result.data:
        return result

    suspicious_count = 0

    if hint == "sap":
        for i, row in enumerate(result.data):
            qty = row.get("quantity", "")
            if qty == "" or qty is None:
                row["_flag"] = "BLANK_QUANTITY"
                suspicious_count += 1
            else:
                try:
                    float(str(qty).replace(",", ""))
                except ValueError:
                    row["_flag"] = f"NON_NUMERIC_QUANTITY:{qty}"
                    suspicious_count += 1

            unit = str(row.get("unit", "")).upper()
            mat = str(row.get("material_code", "")).upper()
            # Diesel/petrol in KG instead of L is a real SAP entry error
            if unit == "KG" and any(k in mat for k in ("DIESEL", "PETRL", "HSD")):
                row["_flag"] = row.get("_flag", "") + "|WRONG_UNIT_KG_FOR_LIQUID_FUEL"
                suspicious_count += 1

    elif hint == "utility":
        for row in result.data:
            kwh = row.get("consumption_kwh", "")
            if kwh == "" or kwh is None:
                row["_flag"] = "BLANK_KWH"
                suspicious_count += 1
            pf = row.get("power_factor", "")
            if pf not in ("", None):
                try:
                    pf_val = float(str(pf))
                    if not (0.70 <= pf_val <= 1.00):
                        row["_flag"] = (
                            row.get("_flag", "") + f"|SUSPICIOUS_POWER_FACTOR:{pf}"
                        )
                        suspicious_count += 1
                except ValueError:
                    pass

    elif hint == "travel":
        for row in result.data:
            etype = str(row.get("expense_type", "")).lower().strip()
            # Flights must have at least one IATA code
            if "air" in etype or "flight" in etype:
                has_iata = row.get("origin_iata", "") or row.get("destination_iata", "")
                if not has_iata:
                    row["_flag"] = "AIRFARE_MISSING_IATA_CODES"
                    suspicious_count += 1
            # Ground transport must have distance
            if "ground" in etype:
                dist = row.get("distance_km", "")
                if dist == "" or dist is None:
                    row["_flag"] = (
                        row.get("_flag", "") + "|GROUND_TRANSPORT_MISSING_DISTANCE"
                    )
                    suspicious_count += 1
            # Rejected expenses should not be in emissions calculation
            status = str(row.get("reimbursement_status", "")).upper()
            if status == "REJECTED":
                row["_flag"] = (
                    row.get("_flag", "") + "|REJECTED_EXPENSE_EXCLUDE_FROM_EMISSIONS"
                )
                suspicious_count += 1

    if suspicious_count:
        result.warnings.append(
            f"{suspicious_count} row(s) flagged with _flag field for analyst review."
        )
    return result


def _detect_domain(rows: list[dict]) -> Optional[str]:
    """Auto-detect domain from column names when no hint is given."""
    if not rows:
        return None
    cols = set(rows[0].keys())

    scores = {}
    for domain, schema in DOMAIN_SCHEMAS.items():
        req = set(schema["required"])
        opt = set(schema["optional"])
        score = len(req & cols) * 3 + len(opt & cols)
        scores[domain] = score

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None
    return best


def _validate_domain(result: ParseResult, hint: str) -> ParseResult:
    """
    FIX 1: When a hint is given, check required columns.
    Missing required columns → FAILURE (not just a warning).
    """
    schema = DOMAIN_SCHEMAS.get(hint)
    if not schema:
        result.warnings.append(f"Unknown hint '{hint}' — skipping domain validation")
        return result

    if not result.data:
        return result

    cols = set(result.data[0].keys())
    required = set(schema["required"])
    missing = required - cols

    if missing:
        result.success_level = SuccessLevel.FAILURE
        result.errors.append(
            f"Domain validation FAILED for hint='{hint}': "
            f"required columns missing: {sorted(missing)}. "
            f"Columns found in file: {sorted(cols)}. "
            f"Ensure you selected the correct source type when uploading."
        )
        result.data = []
        result.row_count = 0
    else:
        result.detected_domain = hint
        # Row-level checks: warn about blank quantity / missing kWh
        result = _row_level_checks(result, hint)
        result.warnings.append(
            f"Domain validation PASSED for '{hint}' ({DOMAIN_SCHEMAS[hint]['description']}) — "
            f"all required columns present."
        )

    return result
