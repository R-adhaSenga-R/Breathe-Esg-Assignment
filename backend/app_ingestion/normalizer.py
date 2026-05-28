"""
Normalizer: converts parsed rows into NormalizedRecord objects.

Emission factors used:
  Scope 1 (fuels):
    Diesel/HSD : 2.68 kg CO2e/litre  — IPCC 2006 / MoEFCC India
    Petrol/MS  : 2.31 kg CO2e/litre  — IPCC 2006
    LPG        : 2.98 kg CO2e/kg     — IPCC 2006
    CNG        : 2.75 kg CO2e/kg     — IPCC 2006
    Furnace oil: 2.96 kg CO2e/litre  — IPCC 2006
    Coal       : 2.42 kg CO2e/kg     — IPCC 2006

  Scope 2 (electricity):
    India grid : 0.716 kg CO2e/kWh   — CEA India 2023

  Scope 3 (travel — DEFRA 2023):
    Domestic flight economy  : 0.255 kg CO2e/km/passenger
    International eco        : 0.195 kg CO2e/km/passenger
    International business   : 0.429 kg CO2e/km/passenger
    Hotel stay               : 20.8  kg CO2e/room-night (India avg)
    Car/taxi                 : 0.171 kg CO2e/km
    Rail                     : 0.041 kg CO2e/km
"""

import math
import logging
from decimal import Decimal
from datetime import datetime
from .models import NormalizedRecord

logger = logging.getLogger(__name__)

# ── Emission factor tables ─────────────────────────────────────────────────────

FUEL_FACTORS = {
    # material_code pattern → (ef kg CO2e per canonical unit, canonical unit)
    'DIESEL'  : (Decimal('2.68'), 'L'),
    'HSD'     : (Decimal('2.68'), 'L'),
    'PETRL'   : (Decimal('2.31'), 'L'),
    'BENZIN'  : (Decimal('2.31'), 'L'),
    'LPG'     : (Decimal('2.98'), 'KG'),
    'CNG'     : (Decimal('2.75'), 'KG'),
    'FURNACE' : (Decimal('2.96'), 'L'),
    'HEIZOEL' : (Decimal('2.96'), 'L'),
    'COAL'    : (Decimal('2.42'), 'KG'),
    'STEINKOH': (Decimal('2.42'), 'KG'),
    'ATF'     : (Decimal('2.55'), 'L'),
    'BIOMASS' : (Decimal('0.02'), 'KG'),
}

INDIA_GRID_FACTOR = Decimal('0.716')   # kg CO2e per kWh — CEA 2023

TRAVEL_FACTORS = {
    ('airfare', 'domestic',      'economy')  : Decimal('0.255'),
    ('airfare', 'domestic',      'business') : Decimal('0.510'),
    ('airfare', 'international', 'economy')  : Decimal('0.195'),
    ('airfare', 'international', 'business') : Decimal('0.429'),
    ('hotel',   'any',           'any')      : Decimal('20.8'),
    ('ground',  'any',           'any')      : Decimal('0.171'),
    ('rail',    'any',           'any')      : Decimal('0.041'),
}

# ── Unit conversion to canonical form ─────────────────────────────────────────
# (source_unit → (multiplier_to_canonical, canonical_unit))
# canonical units: L for liquids, KG for mass fuels, KWH for energy, KM for distance

UNIT_CONVERSIONS = {
    # Volume → L
    'L'     : (Decimal('1'),        'L'),
    'LTR'   : (Decimal('1'),        'L'),
    'LITRE' : (Decimal('1'),        'L'),
    'ML'    : (Decimal('0.001'),    'L'),
    'M3'    : (Decimal('1000'),     'L'),
    'GAL'   : (Decimal('3.78541'), 'L'),
    'GALLON': (Decimal('3.78541'), 'L'),
    # Mass → KG
    'KG'    : (Decimal('1'),        'KG'),
    'G'     : (Decimal('0.001'),    'KG'),
    'T'     : (Decimal('1000'),     'KG'),
    'MT'    : (Decimal('1000'),     'KG'),
    'TON'   : (Decimal('1000'),     'KG'),
    'LB'    : (Decimal('0.453592'), 'KG'),
    # Energy → KWH
    'KWH'   : (Decimal('1'),        'KWH'),
    'MWH'   : (Decimal('1000'),     'KWH'),
    'GWH'   : (Decimal('1000000'),  'KWH'),
    'GJ'    : (Decimal('277.778'),  'KWH'),
    'MJ'    : (Decimal('0.277778'), 'KWH'),
    'BTU'   : (Decimal('0.000293'), 'KWH'),
    # Distance → KM
    'KM'    : (Decimal('1'),        'KM'),
    'M'     : (Decimal('0.001'),    'KM'),
    'MI'    : (Decimal('1.60934'),  'KM'),
    'MILES' : (Decimal('1.60934'),  'KM'),
}


def _to_canonical(qty: Decimal, unit: str):
    """
    Convert qty in source unit to (canonical_qty, canonical_unit).
    Returns (qty, unit) unchanged if no conversion found.
    """
    key = unit.upper().strip()
    if key in UNIT_CONVERSIONS:
        multiplier, canonical_unit = UNIT_CONVERSIONS[key]
        return (qty * multiplier).quantize(Decimal('0.0001')), canonical_unit
    return qty, unit  # Unknown unit: return as-is, log warning
    logger.warning("Unknown unit '%s' — skipping normalization", unit)


# ── Airport data ───────────────────────────────────────────────────────────────

AIRPORT_COORDS = {
    'BOM': (19.0896,  72.8656), 'DEL': (28.5562,  77.1000),
    'BLR': (13.1979,  77.7063), 'HYD': (17.2403,  78.4294),
    'MAA': (12.9900,  80.1693), 'CCU': (22.6547,  88.4467),
    'PNQ': (18.5822,  73.9197), 'AMD': (23.0772,  72.6347),
    'LHR': (51.4775,  -0.4614), 'SIN': ( 1.3644, 103.9915),
    'DXB': (25.2532,  55.3657), 'JFK': (40.6413, -73.7781),
    'FRA': (50.0379,   8.5622), 'NRT': (35.7653, 140.3856),
    'SYD': (-33.946, 151.1772), 'SFO': (37.6213,-122.3790),
    'AMS': (52.3086,   4.7639), 'KUL': ( 2.7456, 101.7072),
    'BKK': (13.6900, 100.7501), 'CDG': (49.0097,   2.5479),
}

DOMESTIC_AIRPORTS = {
    'BOM','DEL','BLR','HYD','MAA','CCU','PNQ','AMD',
    'GOI','IXC','JAI','LKO','PAT','BBI','TRV','COK'
}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def get_fuel_factor(material_code: str, description: str = ''):
    """Match material code or description to emission factor."""
    search = (str(material_code) + ' ' + str(description)).upper()
    for key, (ef, unit) in FUEL_FACTORS.items():
        if key in search:
            return ef, unit
    return None, None


# ── Scope 1: SAP fuel ─────────────────────────────────────────────────────────

def normalize_sap_row(row: dict, org, batch) -> NormalizedRecord | None:
    """Convert one parsed SAP row into a NormalizedRecord."""
    qty_raw = row.get('quantity', '')
    if qty_raw in ('', None):
        return None

    try:
        qty = Decimal(str(qty_raw).replace(',', '').strip())
    except Exception:
        logger.warning("SAP row: could not parse quantity '%s'", qty_raw)
        return None

    unit         = str(row.get('unit', '')).upper().strip()
    mat_code     = str(row.get('material_code', ''))
    mat_desc     = str(row.get('material_description', ''))
    posting_date = _parse_date(row.get('posting_date', ''))
    plant        = str(row.get('plant', ''))
    city         = str(row.get('city', ''))
    state        = str(row.get('state', ''))

    ef, canonical_unit = get_fuel_factor(mat_code, mat_desc)

    # Normalise to canonical unit (e.g. ML → L, m³ → L)
    qty_normalized, unit_normalized = _to_canonical(qty, unit)

    # If the emission factor's canonical unit differs from the conversion target,
    # re-convert to match the factor's expected unit.
    if ef and canonical_unit and unit_normalized != canonical_unit:
        qty_normalized, unit_normalized = _to_canonical(qty, canonical_unit)

    co2e = None
    if ef and qty_normalized:
        co2e = (qty_normalized * ef).quantize(Decimal('0.0001'))

    return NormalizedRecord(
        organization           = org,
        scope                  = 'scope1',
        activity_date          = posting_date,
        site_name              = plant,
        location_city          = city,
        location_state         = state,
        fuel_type              = mat_code,
        quantity               = qty,
        quantity_unit          = unit,
        quantity_normalized    = qty_normalized,
        quantity_normalized_unit = unit_normalized or canonical_unit or unit,
        emission_factor        = ef,
        emission_factor_source = 'IPCC 2006 / MoEFCC India',
        co2e_kg                = co2e,
    )


# ── Scope 2: Utility electricity ──────────────────────────────────────────────

def normalize_utility_row(row: dict, org, batch) -> NormalizedRecord | None:
    """Convert one utility billing row into a NormalizedRecord."""
    kwh_raw = row.get('consumption_kwh', '')
    if kwh_raw in ('', None):
        return None

    try:
        kwh = Decimal(str(kwh_raw).replace(',', '').strip())
    except Exception:
        logger.warning("Utility row: could not parse consumption_kwh '%s'", kwh_raw)
        return None

    unit          = str(row.get('unit', 'kWh')).upper().strip()
    billing_start = _parse_date(row.get('billing_period_start', ''))
    billing_end   = _parse_date(row.get('billing_period_end', ''))

    # Normalise to kWh (handles MWh, GWh, GJ, BTU etc.)
    kwh_normalized, unit_normalized = _to_canonical(kwh, unit or 'KWH')

    co2e = (kwh_normalized * INDIA_GRID_FACTOR).quantize(Decimal('0.0001'))

    return NormalizedRecord(
        organization             = org,
        scope                    = 'scope2',
        activity_date            = billing_start,
        site_name                = str(row.get('site_name', '')),
        location_city            = str(row.get('city', '')),
        location_state           = str(row.get('state', '')),
        consumption_kwh          = kwh,
        meter_id                 = str(row.get('meter_id', '')),
        discom                   = str(row.get('discom', '')),
        billing_start            = billing_start,
        billing_end              = billing_end,
        quantity                 = kwh,
        quantity_unit            = unit or 'KWH',
        quantity_normalized      = kwh_normalized,
        quantity_normalized_unit = unit_normalized,
        emission_factor          = INDIA_GRID_FACTOR,
        emission_factor_source   = 'CEA India Grid EF 2023',
        co2e_kg                  = co2e,
    )


# ── Scope 3: Travel expenses ───────────────────────────────────────────────────

def normalize_travel_row(row: dict, org, batch) -> NormalizedRecord | None:
    """Convert one travel expense row into a NormalizedRecord."""
    expense_type = str(row.get('expense_type', '')).lower().strip()
    status       = str(row.get('reimbursement_status', '')).upper()

    if status == 'REJECTED':
        return None

    trip_date = _parse_date(row.get('trip_start_date', ''))

    # ── Flight ──────────────────────────────────────────────────────────────
    if 'air' in expense_type or 'flight' in expense_type:
        orig_iata    = str(row.get('origin_iata', '')).strip().upper()
        dest_iata    = str(row.get('destination_iata', '')).strip().upper()
        dist_raw     = row.get('distance_km', '')
        travel_class = str(row.get('travel_class', 'Economy')).lower()

        if dist_raw in ('', None) and orig_iata in AIRPORT_COORDS and dest_iata in AIRPORT_COORDS:
            lat1, lon1 = AIRPORT_COORDS[orig_iata]
            lat2, lon2 = AIRPORT_COORDS[dest_iata]
            dist = Decimal(str(round(haversine_km(lat1, lon1, lat2, lon2), 2)))
        elif dist_raw not in ('', None):
            try:
                dist = Decimal(str(dist_raw))
            except Exception:
                dist = None
        else:
            dist = None

        haul = ('domestic'
                if orig_iata in DOMESTIC_AIRPORTS and dest_iata in DOMESTIC_AIRPORTS
                else 'international')
        cls  = 'business' if 'business' in travel_class else 'economy'
        ef   = TRAVEL_FACTORS.get(
            ('airfare', haul, cls),
            TRAVEL_FACTORS.get(('airfare', 'international', 'economy'))
        )
        co2e = (dist * ef).quantize(Decimal('0.0001')) if dist and ef else None

        return NormalizedRecord(
            organization             = org,
            scope                    = 'scope3',
            activity_date            = trip_date,
            travel_type              = 'airfare',
            origin                   = orig_iata,
            destination              = dest_iata,
            distance_km              = dist,
            travel_class             = cls,
            employee_id              = str(row.get('employee_id', '')),
            quantity                 = dist,
            quantity_unit            = 'KM',
            quantity_normalized      = dist,
            quantity_normalized_unit = 'KM',
            emission_factor          = ef,
            emission_factor_source   = 'DEFRA 2023',
            co2e_kg                  = co2e,
        )

    # ── Rail ─────────────────────────────────────────────────────────────────
    elif 'rail' in expense_type or 'train' in expense_type:
        dist_raw = row.get('distance_km', '')
        try:
            dist = Decimal(str(dist_raw)) if dist_raw not in ('', None) else None
        except Exception:
            dist = None

        ef   = TRAVEL_FACTORS[('rail', 'any', 'any')]
        co2e = (dist * ef).quantize(Decimal('0.0001')) if dist else None

        return NormalizedRecord(
            organization             = org,
            scope                    = 'scope3',
            activity_date            = trip_date,
            travel_type              = 'rail',
            origin                   = str(row.get('origin', '')),
            destination              = str(row.get('destination_city', '')),
            distance_km              = dist,
            employee_id              = str(row.get('employee_id', '')),
            quantity                 = dist,
            quantity_unit            = 'KM',
            quantity_normalized      = dist,
            quantity_normalized_unit = 'KM',
            emission_factor          = ef,
            emission_factor_source   = 'DEFRA 2023',
            co2e_kg                  = co2e,
        )

    # ── Hotel ────────────────────────────────────────────────────────────────
    elif 'hotel' in expense_type:
        nights_raw = row.get('nights', '')
        try:
            nights = Decimal(str(nights_raw)) if nights_raw else Decimal('1')
        except Exception:
            nights = Decimal('1')

        ef   = TRAVEL_FACTORS[('hotel', 'any', 'any')]
        co2e = (nights * ef).quantize(Decimal('0.0001'))

        return NormalizedRecord(
            organization             = org,
            scope                    = 'scope3',
            activity_date            = trip_date,
            travel_type              = 'hotel',
            destination              = str(row.get('destination_city', '')),
            employee_id              = str(row.get('employee_id', '')),
            quantity                 = nights,
            quantity_unit            = 'NIGHTS',
            quantity_normalized      = nights,
            quantity_normalized_unit = 'NIGHTS',
            emission_factor          = ef,
            emission_factor_source   = 'DEFRA 2023',
            co2e_kg                  = co2e,
        )

    # ── Ground / Car / Taxi ──────────────────────────────────────────────────
    elif 'ground' in expense_type or 'car' in expense_type or 'taxi' in expense_type:
        dist_raw = row.get('distance_km', '')
        try:
            dist = Decimal(str(dist_raw)) if dist_raw not in ('', None) else None
        except Exception:
            dist = None

        ef   = TRAVEL_FACTORS[('ground', 'any', 'any')]
        co2e = (dist * ef).quantize(Decimal('0.0001')) if dist else None

        return NormalizedRecord(
            organization             = org,
            scope                    = 'scope3',
            activity_date            = trip_date,
            travel_type              = 'ground',
            destination              = str(row.get('destination_city', '')),
            distance_km              = dist,
            employee_id              = str(row.get('employee_id', '')),
            quantity                 = dist,
            quantity_unit            = 'KM',
            quantity_normalized      = dist,
            quantity_normalized_unit = 'KM',
            emission_factor          = ef,
            emission_factor_source   = 'DEFRA 2023',
            co2e_kg                  = co2e,
        )

    logger.warning("Travel row: unrecognised expense_type '%s' — skipping", expense_type)
    return None


# ── Date parser ───────────────────────────────────────────────────────────────

def _parse_date(val):
    if not val or val == '':
        return None
    formats = ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y',
               '%m/%d/%Y', '%Y%m%d', '%d-%m-%Y']
    val = str(val).strip()
    for fmt in formats:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    logger.warning("Could not parse date '%s'", val)
    return None