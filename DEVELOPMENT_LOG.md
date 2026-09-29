# GeoLedger — Development Log

## Entry: September 23, 2026

### 1. Architectural Design & Philosophy
Built GeoLedger strictly adhering to the core principle: **Evidence-first, human-in-the-loop decision support**. The system NEVER makes legal ownership determinations, declares fraud as a legal fact, or fabricates data. Instead, it aggregates documents into a canonical **Parcel Digital Twin**, surfaces discrepancies with explicit reasoning, and presents verified evidence to revenue officials.

### 2. Implementation Progression

- **Backend Architecture**:
  - FastAPI with async lifespan, CORS, and Pydantic Settings
  - 21 SQLAlchemy 2.0 ORM models covering user authentication, document storage, OCR blocks, extracted fields, canonical parcels, mutations, registrations, discrepancies, evidence items, GIS geometries, verification cases, and audit logs.
  - JWT authentication using standard PBKDF2-HMAC-SHA256 (100,000 iterations) with salted hashes.

- **Document Processing & OCR**:
  - Secure upload with MIME validation, SHA-256 integrity hash verification, and UUID storage.
  - PyMuPDF 300 DPI page rendering and OpenCV image enhancement (grayscale, CLAHE contrast, adaptive thresholding).
  - Provider-agnostic OCR architecture (Tesseract / PaddleOCR / Local Fallback) preserving bounding box coordinates and confidence.
  - 23 land record field extractors with normalization (RapidFuzz token matching, unit conversion to acres, date normalization).

- **Parcel Intelligence & Contradiction Engine**:
  - Automatic identity resolution linking multiple documents to a single parcel based on survey number and location.
  - Pairwise multi-document reconciliation detecting phonetic spelling variations (Das vs Dey) and chronology breaks.
  - Land record timeline reconstruction (1998 to 2024) highlighting unrecorded transfers and name reversions.

- **GIS Cadastral Module**:
  - Shapely and PyProj spatial calculations using EPSG:32645 (UTM Zone 45N) for accurate geodesic area measurement.
  - Tolerance-based area variance comparison against document recorded areas.

- **Human Verification & Feedback Loop**:
  - Interactive case management allowing revenue officers to approve, correct, reject, or comment.
  - Dedicated `FeedbackSample` dataset storing AI predictions vs human ground truth corrections for AI fine-tuning without overwriting original extractions.

- **Full Frontend Integration**:
  - Interactive HTML5/CSS3/JavaScript interface served directly by FastAPI.
  - Real-time Dashboard, Document Management, Parcel Digital Twin, Verification Center, Leaflet.js GIS Map, and System Audit Trail.
  - All pages connected to live REST endpoints.

### 3. Verification & Testing
- Developed 5 focused integration test suites and 1 master end-to-end test suite (`test_e2e_master.py`).
- 100% test pass rate across all 12 stages of the land record digitization and validation workflow.
