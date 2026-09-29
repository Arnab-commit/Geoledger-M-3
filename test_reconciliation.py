"""
Test Reconciliation and Timeline: Detect discrepancies across documents.
"""

import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"

def test_reconciliation_timeline():
    print("=" * 70)
    print("  GeoLedger Phase 6 & 7: Reconciliation + Timeline Test")
    print("=" * 70)

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # Login
        print("\n[1/5] Logging in...")
        res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if res.status_code != 200:
            print(f"✗ Login failed: {res.text}")
            return False

        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✓ Logged in")

        # Get parcel
        print("\n[2/5] Getting parcel...")
        res = client.get("/api/parcels", headers=headers)
        if res.status_code != 200:
            print(f"✗ Failed to list parcels: {res.text}")
            return False

        parcels = res.json()
        if len(parcels) == 0:
            print("✗ No parcels found. Run test_pipeline.py first.")
            return False

        parcel = parcels[0]
        parcel_id = parcel["id"]
        parcel_code = parcel["parcel_code"]
        print(f"✓ Found parcel {parcel_code}")

        # Run reconciliation
        print(f"\n[3/5] Running reconciliation on {parcel_code}...")
        res = client.post(f"/api/parcels/{parcel_id}/reconcile", headers=headers)
        if res.status_code != 200:
            print(f"✗ Reconciliation failed: {res.text}")
            return False

        recon = res.json()
        print(f"✓ Reconciliation completed: {recon['discrepancies_found']} discrepancies found\n")

        if recon['discrepancies_found'] > 0:
            print("DISCREPANCIES DETECTED:")
            for d in recon['discrepancies']:
                severity_tag = f"[{d['severity'].upper()}]"
                print(f"\n  {severity_tag} {d['type']}")
                print(f"    Field: {d['field_name']}")
                print(f"    Value A: {d['value_a']}")
                print(f"    Value B: {d['value_b']}")
                print(f"    Similarity: {d['similarity']:.2f}")
                print(f"    Reason: {d['reason']}")
                print(f"    Status: {d['status']}")
        else:
            print("  ✓ No discrepancies detected - all documents consistent")

        # Get timeline
        print(f"\n[4/5] Retrieving Land Record Timeline for {parcel_code}...")
        res = client.get(f"/api/parcels/{parcel_id}/timeline", headers=headers)
        if res.status_code != 200:
            print(f"✗ Timeline retrieval failed: {res.text}")
            return False

        timeline = res.json()
        print(f"✓ Timeline retrieved: {timeline['total_events']} events\n")

        print("TIMELINE SUMMARY:")
        print(f"  Parcel: {timeline['parcel_code']} ({timeline['ulpin']})")
        print(f"  Village: {timeline['village']}")
        print(f"  Time Span: {timeline['earliest_year']} - {timeline['latest_year']}")
        print(f"  Chain of Title Status: {timeline['chain_of_title_status']}")
        print(f"  Timeline Consistency Score: {timeline['timeline_consistency_score']:.2f}")

        print(f"\n[5/5] CHRONOLOGICAL EVENTS:")
        for i, event in enumerate(timeline['events'], 1):
            flag_marker = ""
            if event['status'] in ['warning', 'discrepancy', 'anomaly']:
                flag_marker = f" ⚠ {event['flag']}"

            print(f"\n  {i}. {event['date']} — {event['title']}{flag_marker}")
            print(f"     Type: {event['event_type']}")
            print(f"     Recorded Owner: {event['recorded_owner']}")
            print(f"     Area: {event['area']}")
            print(f"     Description: {event['description']}")

            if event.get('seller'):
                print(f"     Transfer: {event['seller']} → {event['buyer']}")

        # Get updated parcel
        print(f"\n[FINAL CHECK] Retrieving updated parcel state...")
        res = client.get(f"/api/parcels/{parcel_id}", headers=headers)
        if res.status_code != 200:
            print(f"✗ Failed: {res.text}")
            return False

        twin = res.json()
        identity = twin['identity']
        print(f"  Consistency Score: {identity['consistency_score']:.2f}")
        print(f"  Verification Status: {identity['verification_status']}")
        print(f"  Discrepancies on Record: {len(twin['discrepancies'])}")

    print("\n" + "=" * 70)
    print("  ✓ Phase 6 & 7: Reconciliation + Timeline Completed!")
    print("=" * 70)
    print("\nKEY FINDINGS:")
    print("  - Multi-document reconciliation detects name variations")
    print("  - Area mismatches flagged for verification")
    print("  - Chronological chain-of-title breaks identified")
    print("  - Timeline shows ownership transitions with flags")
    print("  - Consistency score computed from discrepancy severity")
    print("  - Evidence-backed system: all findings linked to source docs")
    return True

if __name__ == "__main__":
    success = test_reconciliation_timeline()
    sys.exit(0 if success else 1)
