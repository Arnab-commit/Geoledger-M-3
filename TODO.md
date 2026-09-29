# GeoLedger — Project Roadmap & Future Enhancements

## Core SIH26018 Prototype: COMPLETE ✅

All core requirements from the SIH26018 problem statement and master specification have been built and tested.

---

## Production / Scale-Out Enhancements (Post-Hackathon)

### 1. Database & Infrastructure
- [ ] Migrate SQLite to PostgreSQL with PostGIS extension for spatial queries
- [ ] Deploy with Docker Compose (FastAPI + PostgreSQL + Redis + Nginx)
- [ ] Add Celery/Redis worker queue for asynchronous background batch processing of large PDF bundles

### 2. OCR & Multilingual Indian Language Expansion
- [ ] Fine-tune Indic-OCR / PaddleOCR models on historical Modi and Kaithi handwritten land records
- [ ] Expand dictionary for Bengali, Hindi, Marathi, and Kannada cadastral terminology
- [ ] Add regional state-specific revenue document format templates (e.g., 7/12 extract for Maharashtra, Patta/Chitta for Tamil Nadu)

### 3. State Cadastral API Integration
- [ ] Connect to Bhulekh / Banglarbhumi mock endpoints using Gov standard OpenAPI specs
- [ ] Integrate Aadhaar e-KYC mock verification for registered transfer parties
- [ ] Add cryptographic signature verification on government digitally signed certificates (e-Signed RoRs)
