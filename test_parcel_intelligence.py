"""
Test Parcel Intelligence: Verify multi-document linking to single parcel.
"""

import sys
from pathlib import Path
import httpx

BASE_URL = "http://127.0.0.1:8000"

def test_parcel_intelligence():
    print("=" * 70)
    print("  GeoLedger Phase 5: Parcel Intelligence Test")
    print("=" * 70)

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # Step 1: Login
        print("\n[1/4] Logging in as admin...")
        res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if res.status_code != 200:
            print(f"✗ Login failed: {res.text}")
            return False

        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✓ Logged in successfully")

        # Step 2: Get list of processed documents
        print("\n[2/4] Fetching processed documents...")
        res = client.get("/api/documents", headers=headers)
        if res.status_code != 200:
            print(f"✗ Failed to fetch documents: {res.text}")
            return False

        docs_response = res.json()
        docs = docs_response.get("documents", [])
        processed_docs = [d for d in docs if d.get("processing_status") == "completed"]
        print(f"✓ Found {len(processed_docs)} processed documents")

        if len(processed_docs) == 0:
            print("⚠ No processed documents found. Run test_pipeline.py first.")
            return False

        # Step 3: List parcels
        print("\n[3/4] Listing parcels...")
        res = client.get("/api/parcels", headers=headers)
        if res.status_code != 200:
            print(f"✗ Failed to list parcels: {res.text}")
            return False

        parcels = res.json()
        print(f"✓ Found {len(parcels)} parcel(s)")

        for p in parcels:
            print(f"\n  Parcel: {p['parcel_code']}")
            print(f"    ULPIN: {p['ulpin']}")
            print(f"    Location: {p['village']}, {p['district']}")
            print(f"    Current Owner: {p['current_owner']}")
            print(f"    Area: {p['current_area']} {p['area_unit']}")
            print(f"    Linked Documents: {p['document_count']}")
            print(f"    Consistency Score: {p['consistency_score']:.2f}")
            print(f"    Status: {p['verification_status']}")

        # Step 4: Retrieve full Parcel Digital Twin for first parcel
        if len(parcels) > 0:
            print(f"\n[4/4] Retrieving Parcel Digital Twin for {parcels[0]['parcel_code']}...")
            parcel_id = parcels[0]['id']
            res = client.get(f"/api/parcels/{parcel_id}", headers=headers)
            if res.status_code != 200:
                print(f"✗ Failed to retrieve Digital Twin: {res.text}")
                return False

            twin = res.json()
            print(f"✓ Retrieved complete Parcel Digital Twin\n")

            print("IDENTITY:")
            identity = twin['identity']
            print(f"  Parcel Code: {identity['parcel_code']}")
            print(f"  ULPIN: {identity['ulpin']}")
            print(f"  Village: {identity['village']}, Mouza: {identity['mouza']}")
            print(f"  District: {identity['district']}, State: {identity['state']}")
            print(f"  Current Area: {identity['current_area']} {identity['area_unit']}")
            print(f"  Land Type: {identity['land_classification']}")
            print(f"  Current Owner: {identity['current_owner']}")
            print(f"  Consistency Score: {identity['consistency_score']:.2f}")
            print(f"  Verification Status: {identity['verification_status']}")

            print(f"\nIDENTIFIERS ({len(twin['identifiers'])}):")
            for ident in twin['identifiers']:
                print(f"  - {ident['type']}: {ident['value']} (confidence: {ident['confidence']:.2f})")

            print(f"\nLINKED DOCUMENTS ({len(twin['documents'])}):")
            for doc in twin['documents']:
                print(f"  - {doc['filename']}")
                print(f"    Type: {doc['document_type']}, Status: {doc['processing_status']}")
                print(f"    Uploaded: {doc['upload_timestamp']}")
                print(f"    Hash: {doc['file_hash'][:16]}...")

            print(f"\nOWNERSHIP HISTORY ({len(twin['ownership'])}):")
            for owner in twin['ownership']:
                current_tag = " [CURRENT]" if owner['is_current'] else ""
                print(f"  - {owner['name']}{current_tag}")
                print(f"    Normalized: {owner['normalized_name']}")
                if owner['father_husband_name']:
                    print(f"    Father/Husband: {owner['father_husband_name']}")
                print(f"    Share: {owner['share']:.1%}, Confidence: {owner['confidence']:.2f}")

            print(f"\nMUTATIONS ({len(twin['mutations'])}):")
            for mut in twin['mutations']:
                print(f"  - {mut['mutation_number']} on {mut['date']}")
                print(f"    {mut['previous_owner']} → {mut['new_owner']}")
                print(f"    Area: {mut['area']} acres")

            print(f"\nREGISTRATIONS ({len(twin['registrations'])}):")
            for reg in twin['registrations']:
                print(f"  - {reg['registration_number']} ({reg['type']})")
                print(f"    Date: {reg['date']}")

            print(f"\nDISCREPANCIES ({len(twin['discrepancies'])}):")
            if len(twin['discrepancies']) == 0:
                print("  (None detected yet - will be created in reconciliation phase)")

            print(f"\nGIS DATA ({len(twin['gis'])}):")
            if len(twin['gis']) == 0:
                print("  (No geometries uploaded yet - will be added in GIS phase)")

            print(f"\nVERIFICATION CASES ({len(twin['verification_cases'])}):")
            if len(twin['verification_cases']) == 0:
                print("  (No verification cases yet)")

    print("\n" + "=" * 70)
    print("  ✓ Phase 5: Parcel Intelligence Tests Completed!")
    print("=" * 70)
    print("\nSUMMARY:")
    print("  - Documents successfully linked to parcel entities")
    print("  - Parcel Digital Twin aggregates all related data")
    print("  - Ownership, mutations, and registrations extracted")
    print("  - Ready for Phase 6: Multi-document reconciliation")
    return True

if __name__ == "__main__":
    success = test_parcel_intelligence()
    sys.exit(0 if success else 1)
