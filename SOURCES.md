# Source Data Research — Breathe ESG Ingestion Platform

For each of the three ingestion sources, this document covers: the real-world format researched, what the sample data looks like, and what would break in a real deployment.

---

## Source 1: SAP (Fuel & Fleet — Scope 1)

### Real-world format researched

SAP stores fuel consumption in the **Plant Maintenance (PM)** and **Fleet Management** modules. In practice, ESG teams extract this via:
- **Transaction MB51** (material document list) exported to spreadsheet — the most common method
- **SAP Analytics Cloud** scheduled CSV dumps to SFTP
- **SAP BW extractors** for organisations with a data warehouse

A real MB51 export contains columns like `Plant`, `Material`, `Movement Type`, `Quantity`, `Unit of Entry`, `Posting Date`, and `Vendor`. The material code (`MATNR`) identifies the fuel type — e.g., `DIESEL-EU` or `NATGAS-IND`.

### What our sample data looks like

Our sample CSV uses a simplified, pre-mapped schema:

```
date,plant,fuel_type,quantity,unit,cost_inr
2024-01-15,Mumbai Plant,diesel,5000,L,450000
2024-01-15,Delhi Office,natural_gas,1200,m3,84000
```

The `fuel_type` field is already human-readable (`diesel`, `natural_gas`) rather than a SAP material code. This assumes a mapping step has already been performed — either by the SAP export query or by a pre-processing script.

### What would break in a real deployment

1. **Material code mapping**: Real SAP exports use internal material codes (`10000023`) not human-readable names. We would need a `MaterialCodeMapping` table maintained by the client's SAP team.
2. **Unit of measure codes**: SAP uses its own UoM codes (`L` = litres, `M3` = cubic metres, `KWH` = kilowatt-hours). Some codes are non-standard — `TNE` for metric tonnes, `ST` for "each". Our unit normalizer would need a SAP-to-SI lookup table.
3. **Movement type filtering**: Not all material movements represent consumption. Movement type `261` is a goods issue to a cost centre (consumption), but `122` is a return. Ingesting without filtering on movement type would double-count or produce negative emissions.
4. **Multi-currency costs**: `cost_inr` assumes Indian Rupees. Real SAP deployments store cost in the document currency, which may vary by plant.

---

## Source 2: Utility Bills (Electricity — Scope 2)

### Real-world format researched

Utility bills arrive as PDFs (from BESCOM, Tata Power, MSEDCL, etc.) or as structured CSV exports from energy management systems (Schneider Electric EcoStruxure, Siemens Desigo). Some large organisations use **automated meter reading (AMR)** systems that produce 15-minute interval data.

A typical Indian utility bill CSV contains: account number, billing period start/end, units consumed (kWh), tariff category, amount billed, and sometimes reactive energy (kVAr) and power factor data.

### What our sample data looks like

```
account_number,period_start,period_end,utility_type,quantity,unit,provider
BESCOM-MUM-001,2024-01-01,2024-01-31,electricity,42500,kWh,BESCOM
MSEDCL-DEL-002,2024-01-01,2024-01-31,electricity,18900,kWh,MSEDCL
MAHANAGAR-003,2024-01-01,2024-01-31,gas,850,m3,Mahanagar Gas
```

We use a single emission factor for all electricity (India national grid: 0.82 kg CO₂e/kWh). The `provider` field is captured but not yet used in factor selection.

### What would break in a real deployment

1. **Grid emission factors by region**: India's grid emission factor varies by state (SERC). Tamil Nadu's renewable-heavy grid has a lower factor than coal-heavy states like Jharkhand. We use a single national average, which understates emissions for coal-heavy states and overstates for renewable-heavy ones.
2. **Billing period vs. reporting period mismatch**: Utility bills often span two calendar months. Our parser uses `period_start` as the reporting date, which means a January bill covering Dec 28–Jan 27 is attributed entirely to January. This introduces a systematic ~4-day offset in monthly reporting.
3. **PDF extraction**: Real utility bills are PDFs, not CSVs. Extracting structured data from PDFs (especially scanned images from older providers) requires OCR. We assume a pre-processed CSV input.
4. **Market-based vs. location-based Scope 2**: Organisations that have purchased renewable energy certificates (RECs) or signed Power Purchase Agreements (PPAs) should use a market-based emission factor (potentially zero) rather than the grid average. Our model does not currently capture contractual instruments.

---

## Source 3: Travel & Expenses (Business Travel — Scope 3)

### Real-world format researched

Business travel data comes from:
- **Expense management systems**: Concur SAP, Zoho Expense, Expensify — these export to CSV with columns for expense category, amount, date, merchant, and sometimes distance/route
- **Corporate travel management companies (TMCs)**: Egencia, FCM Travel — these can provide detailed itinerary data including origin, destination, cabin class, and distance
- **Manual expense reports**: Excel or PDF submissions from employees

The GHG Protocol's Scope 3 Category 6 guidance recommends distance-based calculation for flights (using ICAO or DEFRA distance factors) and fuel-based calculation for car travel.

### What our sample data looks like

```
employee_id,date,expense_type,origin,destination,distance_km,amount_inr
EMP001,2024-01-10,flight,BOM,DEL,1148,18500
EMP002,2024-01-12,car,Mumbai,,320,4800
EMP003,2024-01-15,rail,Mumbai,Pune,149,650
```

We use DEFRA 2023 factors: flights at 0.255 kg CO₂e/km (economy, including radiative forcing), car at 0.171 kg CO₂e/km, rail at 0.041 kg CO₂e/km.

### What would break in a real deployment

1. **Distance calculation**: Our sample data includes `distance_km` pre-populated. Real expense data rarely includes distance — it includes origin/destination city or airport code. We would need a distance lookup (e.g., the OpenFlights database for airports, or Google Maps Distance Matrix API for road travel).
2. **Cabin class**: DEFRA factors differ significantly by cabin class — business class flights emit roughly 3x more per km than economy due to seat space allocation. Our model assumes economy throughout.
3. **Expense category mapping**: Real expense systems use free-text categories (`"Taxi to Airport"`, `"Uber"`, `"Train BOM-PNQ"`). We would need an NLP classifier or a mapping table to convert these to our `expense_type` enum (`flight`, `car`, `rail`, `taxi`).
4. **Currency**: `amount_inr` assumes Indian Rupees. Multi-currency support would require an exchange rate table for amount-based (spend-based) fallback calculations when distance data is unavailable.
5. **Radiative forcing for flights**: The science on aviation radiative forcing (the non-CO₂ warming effects of contrails and NOx at altitude) is contested. DEFRA includes an RF multiplier; the GHG Protocol does not mandate it. Our current implementation includes RF in the flight factor, which should be documented for the evaluator.
