# GeoLedger — Architecture

## System Overview

GeoLedger is an evidence-backed land-record intelligence and validation layer.

It does NOT replace DILRMP or existing land-record databases.
It complements them by providing reconciliation, contradiction detection, and quality control.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                     FRONTEND                            │
│  HTML/CSS/JS  │  Leaflet.js  │  Charts                  │
└────────────────────────┬────────────────────────────────┘
                         │ REST API
┌────────────────────────┴────────────────────────────────┐
│                   API LAYER (FastAPI)                    │
│  Upload │ Parcels │ Validation │ Verification │ GIS     │
│  Audit  │ Admin   │ Auth       │ Health                 │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│                  SERVICE LAYER                          │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Document │  │   OCR    │  │Extraction│             │
│  │ Service  │  │ Service  │  │ Service  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Normalize │  │Reconcile │  │Contradict│             │
│  │ Service  │  │ Engine   │  │ Engine   │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Evidence │  │Confidence│  │   GIS    │             │
│  │ Engine   │  │ Engine   │  │ Service  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Timeline │  │ Verify   │  │ Feedback │             │
│  │ Service  │  │ Service  │  │ Service  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐                            │
│  │  Audit   │  │ Parcel   │                            │
│  │ Service  │  │ Identity │                            │
│  └──────────┘  └──────────┘                            │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────┐
│              DATA / PROVIDER LAYER                      │
│                                                         │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │
│  │ SQLite  │  │  OCR    │  │   GIS   │  │  File   │  │
│  │   DB    │  │Provider │  │Provider │  │ Storage │  │
│  │(→PG)   │  │(Tess/   │  │(Shapely)│  │ (Local) │  │
│  │         │  │ Paddle) │  │         │  │         │  │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Core Design Principles

1. **Evidence-first**: Every AI output is traceable to source document, page, and bounding box
2. **Original preserved**: Source documents are never modified; all derived data is separate
3. **No legal conclusions**: System reports "potential inconsistency", never "fraud" or "illegal"
4. **Provider-agnostic**: OCR, GIS, and AI providers are behind interfaces — swappable
5. **Parcel-centric**: The parcel (not the document) is the central entity
6. **Auditable**: Every significant action is logged with who/what/when

## Technology Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Frontend | HTML/CSS/JS, Leaflet.js | Professional government/enterprise style |
| API | Python FastAPI | Async, OpenAPI docs auto-generated |
| Database | SQLite (prototype) → PostgreSQL (production) | SQLAlchemy ORM |
| OCR | Tesseract/PaddleOCR (when available), local fallback | Provider interface |
| Image Processing | Pillow, OpenCV (when available) | Preprocessing pipeline |
| NLP/Extraction | regex + rule-based, spaCy (when available) | Hybrid approach |
| Similarity | RapidFuzz (when available), built-in fallback | Name/text matching |
| GIS | Shapely, Leaflet.js | Area calculation, boundary comparison |
| Auth | JWT + bcrypt | Role-based access control |

## Database Design

See `backend/models/` for SQLAlchemy models.

Core entities:
- **User** — authentication, roles
- **Document** — uploaded files, metadata, processing state
- **DocumentPage** — individual pages from multi-page documents
- **OcrResult** — raw OCR output with bounding boxes and confidence
- **ExtractedField** — structured fields parsed from OCR output
- **Parcel** — canonical land parcel entity
- **ParcelIdentifier** — survey/khasra/khata/ULPIN identifiers
- **ParcelDocument** — document-to-parcel relationships
- **Owner** — ownership records
- **OwnershipEvent** — ownership transitions
- **Mutation** — mutation records
- **Registration** — registration records
- **Discrepancy** — detected inconsistencies with evidence
- **Evidence** — source evidence linking AI output to document regions
- **VerificationCase** — human review cases
- **VerificationAction** — reviewer decisions
- **FeedbackSample** — human corrections for future training
- **AuditLog** — system-wide audit trail
- **GisGeometry** — parcel spatial data

## Processing Pipeline

```
Upload → Preprocessing → OCR → Extraction → Normalization
    → Parcel Identity → Reconciliation → Contradiction Detection
    → Confidence Scoring → Evidence Assembly → Verification Queue
```

## State Adapters

State-specific rules are loaded from `backend/state_adapters/`:
- Field aliases (dag vs khasra vs survey)
- Document types
- Area units
- Date formats
- Identifier patterns
- Validation rules

## Security Model

- JWT tokens with expiry
- bcrypt password hashing
- Role-based access: ADMIN, VERIFIER, VIEWER
- UUID filenames (no path traversal)
- SHA-256 document integrity hashes
- CORS configuration
- Input validation on all endpoints
