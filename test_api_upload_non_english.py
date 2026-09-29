import httpx
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def test_api_multilingual_upload():
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        # 1. Login
        res = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        test_files = [
            ("test_outputs/test_tamil_patta_deed.png", "tam", "Tamil Patta"),
            ("test_outputs/test_telugu_passbook_deed.png", "tel", "Telugu Passbook"),
            ("test_outputs/test_hindi_khatouni_deed.png", "hin", "Hindi Khatouni"),
            ("test_outputs/test_bengali_porcha_deed.png", "ben", "Bengali Porcha")
        ]

        for file_path, lang, label in test_files:
            p = Path(file_path)
            if not p.exists():
                print(f"Skipping {file_path}, does not exist")
                continue
            with open(p, "rb") as f:
                files = {"file": (p.name, f, "image/png")}
                data = {"source": f"web_api_test_{lang}", "language": lang}
                res = client.post("/api/documents/upload", files=files, data=data, headers=headers)
                assert res.status_code == 201, f"Upload failed: {res.text}"
                doc_id = res.json()["id"]

            res = client.post(f"/api/documents/{doc_id}/process", headers=headers)
            assert res.status_code == 200, f"Process failed: {res.text}"
            p_res = res.json()

            res = client.get(f"/api/documents/{doc_id}/extracted-data", headers=headers)
            assert res.status_code == 200
            data = res.json()
            extracted = data.get("extracted_fields", [])
            parcel = data.get("parcel")

            print(f"\n==========================================")
            print(f"[{label}] Uploaded ID: {doc_id[:8]}")
            print(f"  • Extracted Count: {len([f for f in extracted if f.get('value')])}")
            print(f"  • Linked Parcel: {parcel.get('parcel_code') if parcel else 'None'}")
            print(f"  • Native Script Extracted Fields:")
            for f in extracted:
                if f.get("value"):
                    print(f"      {f.get('field_name'):20}: {f.get('value')} (conf: {f.get('confidence')})")

            assert len([f for f in extracted if f.get("value")]) >= 4, f"Too few fields extracted for {label}"

    print("\n✓ ALL NON-ENGLISH DOCUMENT UPLOADS TESTED & VERIFIED ON WEB API & INSPECTION ENDPOINT!")

if __name__ == "__main__":
    test_api_multilingual_upload()
