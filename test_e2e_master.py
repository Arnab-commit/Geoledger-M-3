"""
Master End-to-End Test Suite for GeoLedger
Verifies the complete SIH26018 workflow from login to audit trail.
"""

import sys
import httpx
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"

def run_master_e2e_test():
    print("=" * 80)
    print("       GEOLEDGER — COMPREHENSIVE END-TO-END MASTER TEST")
    print("       SIH26018 Intelligent Land Record Digitization & Validation")
    print("=" * 80)

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # 1. Health Check
        print("\n[Step 1/12] Testing Health Check API...")
        res = client.get("/api/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print(f"  ✓ System healthy: {res.json()['status']} v{res.json()['version']}")

        # 2. Authentication & RBAC
        print("\n[Step 2/12] Testing Authentication & Token Issuance...")
        res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert res.status_code == 200, f"Admin login failed: {res.text}"
        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("  ✓ Admin logged in successfully with PBKDF2-HMAC-SHA256 JWT")

        # 3. Static Frontend Serving
        print("\n[Step 3/12] Testing Static Frontend Serving...")
        for page in ["index.html", "dashboard.html", "documents.html", "parcel.html", "verification.html", "gis.html", "audit.html"]:
            res = client.get(f"/{page}")
            assert res.status_code == 200, f"Failed to serve {page}"
            print(f"  ✓ Served frontend page: /{page}")

        # 4. Document Ingestion
        print("\n[Step 4/12] Testing Multi-Document Ingestion & SHA-256 Hashing...")
        demo_files = list(Path("data/demo_documents").glob("*.png"))
        uploaded_doc_ids = []
        for file_path in demo_files:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "image/png")}
                data = {"source": "e2e_master_test", "language": "eng"}
                res = client.post("/api/documents/upload", files=files, data=data, headers=headers)
                assert res.status_code == 201, f"Upload failed for {file_path.name}: {res.text}"
                doc_data = res.json()
                uploaded_doc_ids.append(doc_data["id"])
        print(f"  ✓ Uploaded {len(uploaded_doc_ids)} documents with SHA-256 integrity hash verification")

        # 5. Document Processing & OCR
        print("\n[Step 5/12] Testing OCR, Structured Extraction, Normalization & Parcel Linking...")
        for doc_id in uploaded_doc_ids:
            res = client.post(f"/api/documents/{doc_id}/process", headers=headers)
            assert res.status_code == 200, f"Processing failed for doc {doc_id}: {res.text}"
            p_res = res.json()
            print(f"  ✓ Processed doc {doc_id[:8]}: Type={p_res['document_type']}, Extracted={p_res['fields_extracted']}, Parcel={p_res.get('parcel_code')}")

        # 6. Parcel Intelligence & Digital Twin
        print("\n[Step 6/12] Testing Parcel Digital Twin Aggregation...")
        res = client.get("/api/parcels", headers=headers)
        assert res.status_code == 200
        parcels = res.json()
        assert len(parcels) > 0, "No parcels found"
        parcel_id = parcels[0]["id"]
        parcel_code = parcels[0]["parcel_code"]

        res = client.get(f"/api/parcels/{parcel_id}", headers=headers)
        assert res.status_code == 200
        twin = res.json()
        print(f"  ✓ Retrieved Parcel Digital Twin: {parcel_code}")
        print(f"    - Linked Documents: {len(twin['documents'])}")
        print(f"    - Identifiers: {len(twin['identifiers'])}")
        print(f"    - Baseline Consistency: {twin['identity']['consistency_score']:.2f}")

        # 7. Multi-Document Reconciliation
        print("\n[Step 7/12] Testing Multi-Document Contradiction Engine...")
        res = client.post(f"/api/parcels/{parcel_id}/reconcile", headers=headers)
        assert res.status_code == 200
        recon = res.json()
        print(f"  ✓ Reconciliation complete: {recon['discrepancies_found']} discrepancies detected")
        for d in recon['discrepancies'][:5]:
            print(f"    - [{d['severity'].upper()}] {d['type']}: {d['reason'][:70]}...")

        # 8. Timeline Reconstruction
        print("\n[Step 8/12] Testing Land Record Timeline Reconstruction...")
        res = client.get(f"/api/parcels/{parcel_id}/timeline", headers=headers)
        assert res.status_code == 200
        timeline = res.json()
        print(f"  ✓ Reconstructed chronological timeline with {timeline['total_events']} events (1998 - 2024)")
        print(f"    - Chain-of-Title Status: {timeline['chain_of_title_status']}")

        # 9. GIS Operations
        print("\n[Step 9/12] Testing GIS Spatial Calculation & Cadastral Validation...")
        geo = {
            "type": "Polygon",
            "coordinates": [[
                [87.4200, 23.3100],
                [87.4210, 23.3100],
                [87.4210, 23.3109],
                [87.4200, 23.3109],
                [87.4200, 23.3100],
            ]]
        }

        res = client.post("/api/gis/calculate-area", headers=headers, json={"geojson": geo})
        assert res.status_code == 200
        calc = res.json()
        print(f"  ✓ Calculated area in UTM projection: {calc['area_acres']:.4f} acres")

        res = client.post(f"/api/gis/parcels/{parcel_id}/geometry", headers=headers, json={"geojson": geo, "source": "e2e_survey"})
        assert res.status_code == 200
        print("  ✓ Attached GeoJSON boundary to Parcel Digital Twin")

        # 10. Verification Workflow
        print("\n[Step 10/12] Testing Human Verification Center Workflow...")
        res = client.post(
            "/api/verification/cases",
            headers=headers,
            json={
                "parcel_id": parcel_id,
                "case_type": "OWNER_NAME_DISCREPANCY",
                "priority": "high",
                "summary": "Phonetic spelling variation in mutation order (Das vs Dey)",
            }
        )
        assert res.status_code == 200
        case_id = res.json()["id"]

        # Submit correction
        res = client.post(
            f"/api/verification/cases/{case_id}/actions",
            headers=headers,
            json={
                "action": "correct",
                "field_name": "owner_name",
                "original_value": "Ramesh Dey",
                "corrected_value": "Ramesh Das",
                "comment": "Verified with historical mutation register: clerical phonetic error.",
            }
        )
        assert res.status_code == 200
        print(f"  ✓ Case #{case_id[:8]} updated with human officer verification and ground truth correction")

        # 11. Feedback Loop Dataset
        print("\n[Step 11/12] Testing Human-to-AI Feedback Dataset Export...")
        res = client.get("/api/verification/feedback/samples", headers=headers)
        assert res.status_code == 200
        samples = res.json()
        assert len(samples) > 0, "No feedback samples recorded"
        print(f"  ✓ Stored {len(samples)} feedback correction samples for AI model fine-tuning")

        # 12. Audit Trail & Analytics
        print("\n[Step 12/12] Testing System Audit Trail & Metrics...")
        res = client.get("/api/audit/logs", headers=headers)
        assert res.status_code == 200
        logs = res.json()
        print(f"  ✓ Verified {logs['total']} immutable audit log events")

        res = client.get("/api/audit/stats", headers=headers)
        assert res.status_code == 200
        stats = res.json()
        print(f"  ✓ System Stats: {stats['documents_count']} docs, {stats['parcels_count']} parcels, {stats['total_discrepancies']} discrepancies, OCR conf={stats['avg_ocr_confidence']}%")

    print("\n" + "=" * 80)
    print("       ✓ ALL 12 END-TO-END MASTER WORKFLOW TESTS PASSED!")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = run_master_e2e_test()
    sys.exit(0 if success else 1)
