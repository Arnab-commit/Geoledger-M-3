# GeoLedger Demo Documents

This directory contains **synthetic demo land records** created for testing and demonstration purposes.

## ⚠️ Important Notice

**THESE ARE NOT REAL GOVERNMENT RECORDS.**

All documents in this folder are artificially generated for the Smart India Hackathon 2026 prototype demonstration. They simulate the structure and content of Indian land records but contain fictional data.

---

## Document Set: Survey No. 124, Village Sonapur

These 5 documents trace the ownership history of a single land parcel (Survey No. 124) across 26 years (1998–2024).

### Documents

1. **ror_1998.png** — Record of Rights (1998)
   - Owner: **Gopal Kumar**
   - Area: 2.50 Acres

2. **sale_deed_2005.png** — Sale Deed (2005)
   - Seller: **Gopal Kumar**
   - Buyer: **Ramesh Das**
   - Date: 10/05/2005

3. **mutation_2006.png** — Mutation Record (2006)
   - Previous Owner: **Ramesh Das**
   - New Owner: **Ramesh Dey** ⚠️ (spelling variation)
   - Date: 15/03/2006

4. **ror_2014.png** — Record of Rights (2014)
   - Owner: **Ramesh Das**
   - Father: **Suresh Das**

5. **current_record_2024.png** — Land Registration Record (2024)
   - Owner: **Suresh Das** ⚠️ (father now listed as owner)
   - Date: 05/01/2024

---

## Intentional Discrepancies

These documents contain **deliberate inconsistencies** to demonstrate GeoLedger's contradiction detection and reconciliation engine:

### 1. Owner Name Spelling Variation
- **Ramesh Das** (sale deed, RoR 2014)
- **Ramesh Dey** (mutation 2006)

This tests the normalization engine's ability to identify that these may refer to the same person while flagging the discrepancy for human verification.

### 2. Ownership Transition Gap
Expected chain: `Gopal Kumar (1998) → Ramesh Das (2005) → ? → Suresh Das (2024)`

The mutation record shows `Ramesh Das → Ramesh Dey` in 2006, but the 2024 record lists **Suresh Das** (who was previously listed as Ramesh's father).

**Potential issues:**
- Missing inheritance/partition document
- Missing mutation from Ramesh to Suresh
- Possible data entry error
- Possible name confusion (father/son)

### 3. Chronology Questions
- Mutation (2006) shows transfer to "Ramesh Dey"
- RoR (2014) shows "Ramesh Das" as owner
- Current record (2024) shows "Suresh Das" (father) as owner

This tests the **temporal validation** and **chronology conflict detection** modules.

### 4. Consistent Area
All records show **2.50 Acres** — intentionally consistent to demonstrate that GeoLedger can distinguish between fields with discrepancies and fields that match across documents.

---

## Expected GeoLedger Behavior

When processing these documents, GeoLedger should:

1. **Link all 5 documents to Parcel PL-XXXXXX** (Survey 124, Sonapur)
2. **Construct a timeline** showing ownership transitions
3. **Detect owner name discrepancy** (Das vs Dey) — flag as MEDIUM severity
4. **Detect ownership transition gap** (Ramesh → Suresh without documented transfer) — flag as HIGH severity
5. **Detect chronology inconsistency** (2006 mutation vs 2014 RoR) — flag as MEDIUM severity
6. **Confirm area consistency** — mark as ✅ CONSISTENT
7. **Generate verification cases** for human review
8. **Provide evidence** — link each finding to source document, page, and bounding box

---

## Testing GeoLedger

### Upload Workflow
1. Upload all 5 documents via `/api/documents/upload`
2. Trigger OCR processing
3. Link documents to the same parcel
4. Run reconciliation
5. Review detected discrepancies in the verification queue

### Expected Output
- **Parcel Digital Twin** page shows all 5 documents linked
- **Timeline** displays ownership events from 1998–2024
- **Discrepancies** tab lists 3-4 detected issues with severity levels
- **Evidence** viewer allows clicking to see source document regions
- **Verification Queue** contains flagged cases for human review

---

## File Specifications

- **Format**: PNG images
- **Dimensions**: 1200×1600 pixels
- **DPI**: 96 (screen resolution)
- **Color**: Black text on white background
- **Style**: Government document aesthetic (borders, structured layout)
- **Language**: English

For production testing, real scanned documents in multiple Indian languages (Hindi, Bengali, Tamil, etc.) with varying quality, handwriting, and historical formats should be used.

---

**GeoLedger Demo Dataset v1.0**  
*Generated for SIH26018 Prototype*
