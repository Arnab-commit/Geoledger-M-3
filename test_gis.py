"""
Test GIS functionality: Area calculation, UTM projections, geometry management, and spatial validation.
Uses FastAPI TestClient so no live server is required.
"""

import sys
import json
import uuid
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.main import app
from backend.database import SessionLocal, init_db
from backend.models.parcel import Parcel
from backend.models.ownership import Owner

client = TestClient(app)

def test_gis():
    print("=" * 70)
    print("  GeoLedger GIS Integration Test (FastAPI TestClient)")
    print("=" * 70)

    # Initialize DB
    init_db()

    # Step 1: Login
    print("\n[1/5] Authenticating as Administrator...")
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert res.status_code == 200, f"Login failed: {res.text}"
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✓ Logged in successfully")

    # Step 2: Validate Real GeoJSON Geometry & Calculate Area
    print("\n[2/5] Calculating Geodesic Area via Dynamic Indian UTM...")
    # Real polygon in Pune, Maharashtra (~73.85°E, 18.52°N)
    test_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [73.8500, 18.5200],
            [73.8520, 18.5200],
            [73.8520, 18.5215],
            [73.8500, 18.5215],
            [73.8500, 18.5200]
        ]]
    }
    res = client.post(
        "/api/gis/calculate-area",
        headers=headers,
        json={"geojson": test_geojson, "use_projected": True}
    )
    assert res.status_code == 200, f"Area calculation failed: {res.text}"
    area_result = res.json()
    print(f"✓ Geodesic Area Calculated: {area_result['area_acres']:.4f} {area_result['unit']} ({area_result['area_sq_meters']} m²)")
    print(f"  CRS Zone: {area_result['utm_zone']}")
    print(f"  Geometry Type: {area_result['geometry_type']}")
    print(f"  Valid Topology: {area_result['validation']['valid']}")

    # Step 3: Area Variance Comparison
    print("\n[3/5] Comparing Recorded Document Area vs GIS Area...")
    doc_area = 8.50  # acres
    gis_area = area_result['area_acres']

    res = client.post(
        f"/api/gis/compare-area?doc_area={doc_area}&gis_area={gis_area}&tolerance=0.10",
        headers=headers
    )
    assert res.status_code == 200, f"Area comparison failed: {res.text}"
    comp = res.json()
    print(f"✓ Area comparison:")
    print(f"  Document Area: {comp['document_area']:.4f} acres")
    print(f"  GIS Calculated: {comp['gis_area']:.4f} acres")
    print(f"  Variance: {comp['variance_acres']:.4f} acres ({comp['variance_percent']:.2f}%)")
    print(f"  Status: {comp['status']} ({comp['severity']})")
    print(f"  Explanation: {comp['explanation']}")

    # Step 4: Create Test Parcel & Save Cadastral Boundary
    print("\n[4/5] Creating Dynamic Parcel & Attaching Cadastral Geometry...")
    db = SessionLocal()
    unique_id = uuid.uuid4().hex[:6]
    test_code = f"MH-PUN-{unique_id}"
    try:
        p = Parcel(
            id=str(uuid.uuid4()),
            parcel_code=test_code,
            village="Shivajinagar",
            district="Pune",
            state="Maharashtra",
            current_owner="Rajendra Patil",
            current_area=round(gis_area, 4),  # Exactly matching GIS area for MATCH status
            area_unit="acres"
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        parcel_id = p.id
    finally:
        db.close()

    res = client.post(
        f"/api/gis/parcels/{parcel_id}/geometry",
        headers=headers,
        json={
            "geojson": test_geojson,
            "source": "cadastral_survey",
            "is_authoritative": "false"
        }
    )
    assert res.status_code == 200, f"Failed to attach geometry: {res.text}"
    attach_result = res.json()
    print(f"✓ Geometry attached to parcel {test_code}")
    print(f"  GIS ID: {attach_result['gis_id'][:12]}...")
    print(f"  Calculated Area: {attach_result['calculated_area_acres']:.4f} {attach_result['area_unit']}")
    print(f"  Status: {attach_result['comparison']['status']}")
    print(f"  Audit ID: {attach_result['audit_id'][:12]}...")

    # Step 5: Query Full FeatureCollection & Parcel GIS Details
    print("\n[5/5] Fetching Dynamic GIS FeatureCollection and Parcel Details...")
    res = client.get("/api/gis/parcels", headers=headers)
    assert res.status_code == 200
    fc = res.json()
    assert fc["type"] == "FeatureCollection"
    print(f"✓ Retrieved FeatureCollection with {fc['total_features']} total mapped boundaries")

    res = client.get(f"/api/gis/parcels/{parcel_id}", headers=headers)
    assert res.status_code == 200
    details = res.json()
    assert details["parcel"]["current_owner"] == "Rajendra Patil"
    assert details["active_geometry"] is not None
    assert len(details["audit_history"]) >= 1
    print(f"✓ Retrieved Parcel Spatial Record:")
    print(f"  Owner: {details['parcel']['current_owner']}")
    print(f"  Active Geometry Area: {details['active_geometry']['calculated_area']:.4f} acres")
    print(f"  Audit Events Count: {len(details['audit_history'])}")

    print("\n" + "=" * 70)
    print("  ✓ Phase 8: GIS Integration Test Passed with 100% Success!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    success = test_gis()
    sys.exit(0 if success else 1)
