"""
Full System Integration Test: Verification + Feedback loop.
"""

import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"

def test_verification_feedback():
    print("=" * 70)
    print("  GeoLedger Verification + Feedback Loop Test")
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
        print("✓ Logged in")

        # Step 2: Get parcel
        res = client.get("/api/parcels", headers=headers)
        parcels = res.json()
        if not parcels:
            print("✗ No parcels found.")
            return False
        parcel_id = parcels[0]["id"]
        parcel_code = parcels[0]["parcel_code"]

        # Step 3: Create verification case
        print(f"\n[2/4] Creating verification case for {parcel_code}...")
        res = client.post(
            "/api/verification/cases",
            headers=headers,
            json={
                "parcel_id": parcel_id,
                "case_type": "OWNER_NAME_DISCREPANCY",
                "priority": "high",
                "summary": "Owner name spelling discrepancy: Ramesh Das vs Ramesh Dey in 2006 mutation",
            }
        )
        if res.status_code != 200:
            print(f"✗ Failed to create case: {res.text}")
            return False

        case = res.json()
        case_id = case["id"]
        print(f"✓ Created case {case_id[:8]} (Status: {case['status']}, Priority: {case['priority']})")

        # Step 4: Add verification action with correction
        print("\n[3/4] Submitting human correction action...")
        res = client.post(
            f"/api/verification/cases/{case_id}/actions",
            headers=headers,
            json={
                "action": "correct",
                "field_name": "owner_name",
                "original_value": "Ramesh Dey",
                "corrected_value": "Ramesh Das",
                "comment": "Confirmed by revenue officer: Dey was a phonetic clerical error during 2006 manual entry.",
            }
        )
        if res.status_code != 200:
            print(f"✗ Failed to submit action: {res.text}")
            return False

        action_res = res.json()
        print(f"✓ Action recorded: {action_res['action']} -> New Case Status: {action_res['new_case_status']}")

        # Step 5: Check feedback dataset
        print("\n[4/4] Verifying feedback dataset...")
        res = client.get("/api/verification/feedback/samples", headers=headers)
        if res.status_code != 200:
            print(f"✗ Failed to fetch feedback: {res.text}")
            return False

        samples = res.json()
        print(f"✓ Retrieved {len(samples)} feedback samples for AI improvement")
        if samples:
            s = samples[0]
            print(f"  Field: {s['field_name']}")
            print(f"  AI Extracted: '{s['ai_extracted']}'")
            print(f"  Human Corrected: '{s['human_corrected']}'")

    print("\n" + "=" * 70)
    print("  ✓ Verification & Feedback Loop Test Completed Successfully!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    success = test_verification_feedback()
    sys.exit(0 if success else 1)
