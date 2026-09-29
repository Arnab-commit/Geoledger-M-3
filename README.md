# GeoLedger

**Intelligent Land Record Digitization and Validation System**

GeoLedger is an evidence-backed land-record intelligence and validation layer that reconstructs, reconciles, explains, and verifies legacy land records. Built for Smart India Hackathon 2026 (Problem Statement SIH26018).

---

## 🎯 Core Differentiators

GeoLedger does not merely digitize land records. It:

1. **Parcel Digital Twin** — Aggregates multiple documents into one canonical parcel entity with full historical context
2. **Land Record Timeline** — Reconstructs chronological ownership history from fragmented documents
3. **Evidence-Backed Contradiction Engine** — Detects inconsistencies and explains *why* with traceable source evidence
4. **Spatial Reconciliation** — Compares recorded area against GIS-calculated area
5. **Human-AI Feedback Loop** — Learns from human corrections to improve over time

---

## 🏗️ Architecture

```
Frontend (HTML/CSS/JS)
         ↓
REST API (FastAPI)
         ↓
Service Layer (OCR → Extraction → Normalization → Reconciliation → Contradiction Detection)
         ↓
Database (SQLite → PostgreSQL) + GIS (Shapely) + OCR Provider (Tesseract/PaddleOCR/Local)
```

**Key Design Principles:**
- **Evidence-first**: Every AI output is traceable to source document + page + bounding box
- **Original preserved**: Source documents are never modified
- **No legal conclusions**: System reports "potential inconsistency", never "fraud confirmed"
- **Provider-agnostic**: OCR/GIS providers are behind interfaces — swappable
- **Parcel-centric**: The parcel (not individual documents) is the central entity

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+ (tested on 3.14)
- Node.js 24+ (for frontend serving, optional)

### Installation

1. **Clone/extract the project**
   ```powershell
   cd "C:\project GeoLedger"
   ```

2. **Create virtual environment**
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**
   ```powershell
   python -m pip install -r requirements.txt
   ```

4. **Configure environment**
   ```powershell
   Copy-Item .env.example .env
   # Edit .env if needed (default values work for prototype)
   ```

5. **Initialize database**
   The database is automatically initialized on first run.

6. **Run the application**
   ```powershell
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

7. **Access the application**
   Open browser: http://localhost:8000

---

## 👥 Default Users (Prototype)

| Username | Password | Role | Purpose |
|----------|----------|------|---------|
| `admin` | `admin123` | ADMIN | Full system access, user management, configuration |
| `verifier` | `verifier123` | VERIFIER | Upload documents, review discrepancies, correct records |
| `viewer` | `viewer123` | VIEWER | Read-only access, audit trail, reports |

**⚠️ Change these credentials in production!**

---

## 📁 Project Structure

```
GeoLedger/
├── backend/
│   ├── api/              # FastAPI route handlers
│   ├── models/           # SQLAlchemy database models
│   ├── schemas/          # Pydantic request/response schemas
│   ├── services/         # Business logic (OCR, extraction, reconciliation, etc.)
│   ├── rules/            # Validation rule definitions
│   ├── state_adapters/   # State-specific field/terminology mappings
│   ├── ml/               # Machine learning models (future)
│   ├── utils/            # Utility functions
│   ├── config.py         # Configuration management
│   ├── database.py       # SQLite/PostgreSQL connection and initialization
│   ├── logging_config.py # Logging setup
│   └── main.py           # FastAPI application entry point
├── frontend/
│   ├── index.html        # Login page
│   ├── dashboard.html    # Main dashboard
│   ├── documents.html    # Document management
│   ├── parcel.html       # Parcel Digital Twin
│   ├── verification.html # Human verification queue
│   ├── gis.html          # GIS map view
│   ├── audit.html        # Audit trail
│   ├── style.css         # Professional government/enterprise styling
│   └── app.js            # Frontend JavaScript utilities
├── data/                 # SQLite database (auto-created)
├── uploads/              # Uploaded document storage (auto-created)
├── logs/                 # Application logs (auto-created)
├── reports/              # Generated reports (auto-created)
├── migrations/           # Alembic PostgreSQL/PostGIS schema migrations
├── scripts/              # Safe database import utilities
├── docs/database.md      # PostgreSQL setup and SQLite import guide
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
├── README.md             # This file
├── ARCHITECTURE.md       # Detailed architecture documentation
├── IMPLEMENTATION_STATUS.md  # Feature implementation tracker
├── DEVELOPMENT_LOG.md    # Development decisions and blockers
└── TODO.md               # Task list
```

---

## 🔧 Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | HTML5, CSS3, JavaScript (ES6+), Leaflet.js (maps) |
| **API** | Python 3.14, FastAPI, Uvicorn |
| **Database** | SQLite (local/demo) or PostgreSQL + PostGIS (production) |
| **ORM** | SQLAlchemy 2.0 |
| **Migrations** | Alembic |
| **PostgreSQL driver** | Psycopg 3 |
| **Spatial ORM** | GeoAlchemy2 (EPSG:4326 geometry with GiST index) |
| **Authentication** | JWT (python-jose), bcrypt (passlib) |
| **OCR** | Tesseract / PaddleOCR (when available), local regex fallback |
| **Image Processing** | Pillow, OpenCV (when available) |
| **NLP/Extraction** | spaCy (when available), rule-based fallback |
| **Similarity Matching** | RapidFuzz |
| **GIS** | Shapely, Leaflet.js |

See [Database Operations](docs/database.md) for PostgreSQL setup, safe SQLite
import, backup guidance and PostGIS spatial query support.

---

## 📊 Key Features

### Phase 1 — Document Pipeline ✅
- [x] Multi-document upload (PDF, JPG, PNG)
- [x] Secure file handling with SHA-256 integrity hashing
- [x] Document metadata extraction
- [x] Processing state tracking
- [x] OCR provider interface (Tesseract/PaddleOCR/local fallback)

### Phase 2 — Intelligence Layer 🟡
- [ ] Structured field extraction (23 land-record fields)
- [ ] Multi-dimensional confidence scoring
- [ ] Name/number/date/unit normalization
- [ ] Entity resolution (same parcel identification)

### Phase 3 — Differentiation 🟡
- [ ] Parcel Digital Twin aggregation
- [ ] Land Record Timeline reconstruction
- [ ] Cross-document reconciliation
- [ ] Evidence-backed contradiction detection
- [ ] GIS area calculation & comparison

### Phase 4 — Government Workflow ⬜
- [ ] Human verification queue
- [ ] Reviewer correction workflow
- [ ] Audit trail
- [ ] Human→AI feedback dataset

### Phase 5 — Integration ⬜
- [ ] Complete REST API
- [ ] OpenAPI documentation
- [ ] External system integration architecture

---

## 🧪 Testing

```powershell
# Run all tests
pytest

# Run specific test module
pytest tests/test_ocr_service.py

# Run with coverage
pytest --cov=backend --cov-report=html
```

---

## 🗺️ API Endpoints

### Authentication
- `POST /api/auth/register` — Register new user
- `POST /api/auth/login` — Login and receive JWT
- `GET /api/auth/me` — Get current user profile

### Health
- `GET /api/health` — System health check

### Documents (Phase 2)
- `POST /api/upload` — Upload document
- `GET /api/documents` — List documents
- `GET /api/documents/{id}` — Get document details
- `POST /api/documents/{id}/process` — Trigger OCR/extraction

### Parcels (Phase 3)
- `GET /api/parcels` — List parcels
- `GET /api/parcels/{id}` — Get Parcel Digital Twin
- `GET /api/parcels/{id}/timeline` — Get parcel timeline
- `GET /api/parcels/{id}/discrepancies` — Get detected inconsistencies

### Verification (Phase 4)
- `GET /api/verification/queue` — Get verification queue
- `POST /api/verification/{case_id}/action` — Submit verification action

### GIS (Phase 3)
- `POST /api/gis/calculate-area` — Calculate polygon area
- `POST /api/gis/compare-area` — Compare recorded vs GIS area

### Audit
- `GET /api/audit` — Get audit logs

---

## 🎨 Demo Data

Demo datasets with realistic inconsistencies are located in `data/demo_documents/`.

**Important:** All demo data is clearly labelled as **SAMPLE/PROTOTYPE DATA** and should never be presented as authentic government records.

---

## 🔒 Security Notes

**Prototype security measures:**
- JWT authentication with bcrypt password hashing
- Role-based access control (ADMIN, VERIFIER, VIEWER)
- File extension & MIME type validation
- File size limits
- SHA-256 document integrity hashing
- SQL injection protection (SQLAlchemy ORM)
- CORS configuration

**Production hardening required:**
- HTTPS/TLS
- Multi-factor authentication
- Encryption at rest
- Rate limiting
- Malware scanning
- Secure secrets management (not .env)
- Private database with restricted access
- Regular security audits

**⚠️ This is a prototype. Do not deploy to production without security review.**

---

## 🚫 What GeoLedger Does NOT Do

To maintain clear boundaries and ethical AI use:

- ❌ GeoLedger does NOT determine legal ownership
- ❌ GeoLedger does NOT detect fraud as a legal conclusion
- ❌ GeoLedger does NOT automatically approve/reject ownership claims
- ❌ GeoLedger does NOT replace DILRMP or existing land-record systems
- ❌ GeoLedger does NOT guarantee 100% OCR accuracy
- ❌ GeoLedger does NOT treat satellite imagery as cadastral proof
- ❌ GeoLedger does NOT make decisions without human oversight

**Instead, GeoLedger:**
- ✅ Reports "potential inconsistency" with evidence
- ✅ Provides confidence scores as review priority indicators
- ✅ Requires human verification for final decisions
- ✅ Maintains full audit trails
- ✅ Preserves original documents as source evidence

---

## 📈 Roadmap

### Near-term (Hackathon)
- Complete Phase 2 (Extraction + Normalization)
- Complete Phase 3 (Parcel Digital Twin + Timeline + Reconciliation)
- Build demo dataset with realistic inconsistencies
- Polish frontend for judge demonstration

### Medium-term
- Handwriting recognition (TrOCR integration)
- Multi-language support (Tamil, Telugu, Bengali, Marathi)
- Advanced contradiction rules (chronology validation)
- Improved entity resolution
- Model fine-tuning from feedback dataset

### Long-term
- Integration with DILRMP 3.0 APIs
- Integration with ULPIN system
- Integration with registration databases
- Court matter cross-referencing
- Blockchain-based audit trail (if required by policy)

---

## 🤝 Contributing

This is a Smart India Hackathon 2026 prototype. For collaboration or questions, contact the development team.

---

## 📄 License

Prototype developed for Smart India Hackathon 2026. License TBD.

---

## 🙏 Acknowledgments

- **Smart India Hackathon 2026** — Problem Statement SIH26018
- **DILRMP** — Digital India Land Records Modernisation Programme
- **Department of Land Resources, Ministry of Rural Development**

---

**GeoLedger — Reconstructing India's Land Records, One Parcel at a Time**
