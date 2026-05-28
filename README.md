# Breathe ESG — Emissions Ingestion Platform

A multi-tenant ESG data ingestion and review platform supporting Scope 1 (SAP fuel), Scope 2 (utility electricity), and Scope 3 (corporate travel) emissions data.

---

## Quick Start

### Prerequisites
- Python 3.12
- Node.js 18+
- PostgreSQL 14+

---

### 1. Database Setup

```bash
psql -U postgres
CREATE DATABASE breathe_esg;
CREATE USER breathe_user WITH PASSWORD 'breathe123';
GRANT ALL PRIVILEGES ON DATABASE breathe_esg TO breathe_user;
\q
```

---

### 2. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser  # set username + password for admin panel

python manage.py runserver        # runs on http://127.0.0.1:8000
```

---

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev                       # runs on http://localhost:5173
```

---

## Access

| Page | URL |
|---|---|
| **Analyst Dashboard** | https://appealing-cat-production-1790.up.railway.app/dashboard |
| **Django Admin Panel** | https://breathe-esg-assignment-production-f6e4.up.railway.app/admin/ |

### Admin Credentials
```
Username 1 : admin
Password 1 : admin
Username 2 : radha
Password 2 : 12345
```
> Set during `createsuperuser`. Change these if deploying publicly.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/upload/` | Upload SAP / utility / travel CSV |
| `GET` | `/api/records/` | List normalised records (paginated) |
| `POST` | `/api/records/<id>/review/` | Approve / reject / flag a record |
| `POST` | `/api/records/bulk-review/` | Bulk review |
| `GET` | `/api/records/<id>/raw/` | View original source row |
| `GET` | `/api/batches/` | List all upload batches |
| `GET` | `/api/summary/` | CO₂e totals by scope |
| `GET` | `/api/audit-log/` | Full immutable audit trail |

All endpoints accept `?org_id=1` as a query parameter.

---

## Sample Data Files

| File | Source | Scope |
|---|---|---|
| `sap_mb51_alv_export_large.csv` | SAP fuel export | Scope 1 |
| `utility_bills.csv` | Electricity billing | Scope 2 |
| `travel_expenses.csv` | Concur travel export | Scope 3 |

---

## Project Structure

```
breathe-esg/
├── backend/
│   ├── app_ingestion/      # Models, views, normalizer, parsers
│   ├── breathe_esg/        # Django settings, URLs
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/          # Dashboard.jsx, Upload.jsx
│       └── api.js
├── MODEL.md                # Data model design decisions
├── DECISIONS.md            # Engineering decisions & PM questions
├── TRADEOFFS.md            # Deliberate scope cuts
└── SOURCES.md              # Real-world source format research
```

---

## Deployment

Set these environment variables on Railway / Render:

```
SECRET_KEY=<strong-random-key>
DEBUG=False
DATABASE_URL=<provided-by-platform>
ALLOWED_HOSTS=<your-deployed-domain>
CORS_ALLOWED_ORIGINS=<your-frontend-url>
```

Then run:
```bash
python manage.py collectstatic --noinput
python manage.py migrate
```
