"""
Test script for Phase 2 & 3: Upload and Process Demo Documents.
"""

import sys
import os
from pathlib import Path
import httpx

# API URL
BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("=" * 60)
    print("  GeoLedger Phase 2 & 3 Pipeline Test")
    print("=" * 60)

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # Step 1: Login
        print("\n[1/4] Logging in as admin...")
        res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if res.status_code != 200:
            print(f"✗ Login failed: {res.text}")
            return False

        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✓ Logged in successfully. Received JWT token.")

        # Step 2: Upload demo documents
        demo_dir = Path("data/demo_documents")
        demo_files = list(demo_dir.glob("*.png"))
        print(f"\n[2/4] Uploading {len(demo_files)} demo documents...")

        uploaded_docs = []
        for file_path in demo_files:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "image/png")}
                data = {"source": "demo_test", "language": "eng"}
                res = client.post("/api/documents/upload", files=files, data=data, headers=headers)
                if res.status_code != 201:
                    print(f"✗ Upload failed for {file_path.name}: {res.text}")
                    return False
                doc_data = res.json()
                uploaded_docs.append(doc_data)
                print(f"  ✓ Uploaded: {file_path.name} -> ID: {doc_data['id'][:8]} (Hash: {doc_data['file_hash'][:8]}...)")

        # Step 3: Process documents through OCR & Extraction pipeline
        print(f"\n[3/4] Processing documents through OCR, Extraction & Normalization...")
        for doc in uploaded_docs:
            doc_id = doc["id"]
            res = client.post(f"/api/documents/{doc_id}/process", headers=headers)
            if res.status_code != 200:
                print(f"✗ Processing failed for doc {doc_id}: {res.text}")
                return False

            p_res = res.json()
            print(f"  ✓ Processed doc {doc_id[:8]}: Type={p_res['document_type']}, Extracted {p_res['fields_extracted']} fields")

        # Step 4: Verify Database State
        print("\n[4/4] Verifying extracted fields and evidence in database...")
        from backend.database import SessionLocal
        from backend.models.document import Document
        from backend.models.extraction import ExtractedField
        from backend.models.evidence import Evidence
        from backend.models.audit import AuditLog

        db = SessionLocal()
        try:
            doc_count = db.query(Document).count()
            field_count = db.query(ExtractedField).filter(ExtractedField.value != None).count()
            evidence_count = db.query(Evidence).count()
            audit_count = db.query(AuditLog).count()

            print(f"  ✓ Total Documents in DB: {doc_count}")
            print(f"  ✓ Total Non-empty Extracted Fields: {field_count}")
            print(f"  ✓ Total Evidence Items Created: {evidence_count}")
            print(f"  ✓ Total Audit Log Entries: {audit_count}")

            # Sample some extracted data
            print("\nSample Extracted Fields:")
            sample_fields = db.query(ExtractedField).filter(ExtractedField.value != None).limit(8).all()
            for f in sample_fields:
                print(f"  - [{f.field_name}] raw: '{f.value}' -> normalized: '{f.normalized_value}' (conf: {f.confidence:.2f})")

        finally:
            db.close()

    print("\n" + "=" * 60)
    print("  ✓ Phase 2 & 3 Tests Completed Successfully!")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
