"""
Live End-to-End Workflow Test
Tests the complete GeoLedger application workflow through actual HTTP API calls
"""

import httpx
from pathlib import Path

BASE = 'http://127.0.0.1:8000'

def run_live_e2e_test():
    client = httpx.Client(base_url=BASE, timeout=30.0)

    print('=' * 80)
    print('  LIVE APPLICATION END-TO-END WORKFLOW TEST')
    print('=' * 80)
    print()

    # 1. Health check
    r = client.get('/api/health')
    status = r.json()['status']
    print(f'1. Health Check: {r.status_code} -> {status}')
    assert r.status_code == 200

    # 2. Login
    r = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin123'})
    token = r.json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    print(f'2. Admin Login: {r.status_code} -> Token received')
    assert r.status_code == 200

    # 3. Upload a document
    demo_file = Path('data/demo_documents/ror_2014.png')
    with open(demo_file, 'rb') as f:
        files = {'file': (demo_file.name, f, 'image/png')}
        data = {'language': 'eng', 'source': 'e2e_test'}
        r = client.post('/api/documents/upload', files=files, data=data, headers=headers)
    doc_id = r.json()['id']
    print(f'3. Upload Document: {r.status_code} -> {doc_id[:8]}')
    assert r.status_code == 201

    # 4. Process the document
    r = client.post(f'/api/documents/{doc_id}/process', headers=headers)
    doc_type = r.json()['document_type']
    fields = r.json()['fields_extracted']
    print(f'4. Process Document: {r.status_code} -> Type={doc_type}, Fields={fields}')
    assert r.status_code == 200

    # 5. Get parcel list
    r = client.get('/api/parcels', headers=headers)
    parcels = r.json()
    parcel_id = parcels[0]['id']
    parcel_code = parcels[0]['parcel_code']
    print(f'5. List Parcels: {r.status_code} -> {len(parcels)} parcels, selected {parcel_code}')
    assert r.status_code == 200

    # 6. Get parcel digital twin
    r = client.get(f'/api/parcels/{parcel_id}', headers=headers)
    twin = r.json()
    print(f'6. Get Digital Twin: {r.status_code} -> {twin["identity"]["parcel_code"]}, {len(twin["documents"])} docs, {len(twin["ownership"])} owners')
    assert r.status_code == 200

    # 7. Get timeline
    r = client.get(f'/api/parcels/{parcel_id}/timeline', headers=headers)
    timeline = r.json()
    print(f'7. Get Timeline: {r.status_code} -> {timeline["total_events"]} events, status={timeline["chain_of_title_status"]}')
    assert r.status_code == 200

    # 8. Reconcile parcel
    r = client.post(f'/api/parcels/{parcel_id}/reconcile', headers=headers)
    recon = r.json()
    print(f'8. Reconcile Parcel: {r.status_code} -> {recon["discrepancies_found"]} discrepancies found')
    assert r.status_code == 200

    # 9. Get GIS demo polygon
    r = client.get('/api/gis/demo-polygon?survey_no=124&village=Sonapur', headers=headers)
    geom = r.json()
    print(f'9. Get GIS Polygon: {r.status_code} -> {geom["geometry"]["type"]} geometry')
    assert r.status_code == 200

    # 10. Calculate GIS area
    r = client.post('/api/gis/calculate-area', json={'geojson': geom['geometry']}, headers=headers)
    area = r.json()
    print(f'10. Calculate Area: {r.status_code} -> {area["area_acres"]} acres')
    assert r.status_code == 200

    # 11. Create verification case
    r = client.post('/api/verification/cases', json={
        'parcel_id': parcel_id,
        'case_type': 'OWNER_NAME_DISCREPANCY',
        'priority': 'high',
        'summary': 'E2E test case'
    }, headers=headers)
    case_id = r.json()['id']
    print(f'11. Create Verification Case: {r.status_code} -> {case_id[:8]}')
    assert r.status_code == 200

    # 12. Submit verification action
    r = client.post(f'/api/verification/cases/{case_id}/actions', json={
        'action': 'approve',
        'comment': 'E2E test approval'
    }, headers=headers)
    print(f'12. Submit Verification Action: {r.status_code} -> {r.json()["action"]}')
    assert r.status_code == 200

    # 13. Get audit logs
    r = client.get('/api/audit/logs?limit=5', headers=headers)
    logs = r.json()
    print(f'13. Get Audit Logs: {r.status_code} -> {logs["total"]} total events')
    assert r.status_code == 200

    # 14. Get system stats
    r = client.get('/api/audit/stats', headers=headers)
    stats = r.json()
    print(f'14. Get System Stats: {r.status_code} -> {stats["documents_count"]} docs, {stats["parcels_count"]} parcels')
    assert r.status_code == 200

    print()
    print('=' * 80)
    print('  ✓ All 14 workflow steps completed successfully')
    print('=' * 80)

if __name__ == '__main__':
    run_live_e2e_test()
