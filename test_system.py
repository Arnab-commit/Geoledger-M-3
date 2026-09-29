"""
GeoLedger System Test Script

Run this after installation to verify the system is working.
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all critical modules can be imported."""
    print("Testing imports...")
    try:
        from backend.config import settings
        from backend.database import engine, Base, get_db, init_db
        from backend.logging_config import logger
        print("  ✓ Core modules imported")
    except Exception as e:
        print(f"  ✗ Core import failed: {e}")
        return False

    try:
        from backend.models import all_models
        print(f"  ✓ Models imported ({len(all_models)} models)")
    except Exception as e:
        print(f"  ✗ Model import failed: {e}")
        return False

    try:
        from backend.api.auth import router as auth_router
        from backend.api.health import router as health_router
        print("  ✓ API routers imported")
    except Exception as e:
        print(f"  ✗ API router import failed: {e}")
        return False

    return True


def test_database():
    """Test database connection and table creation."""
    print("\nTesting database...")
    try:
        from backend.database import init_db, engine
        from sqlalchemy import text

        # Initialize database
        init_db()
        print("  ✓ Database initialized")

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.fetchone()[0] == 1
        print("  ✓ Database connection working")

        # Check tables
        from backend.database import Base
        table_names = Base.metadata.tables.keys()
        print(f"  ✓ {len(table_names)} tables created")

        return True
    except Exception as e:
        print(f"  ✗ Database test failed: {e}")
        return False


def test_auth():
    """Test authentication functions."""
    print("\nTesting authentication...")
    try:
        from backend.api.auth import hash_password, verify_password, create_access_token

        # Test password hashing (use short password for bcrypt 72-byte limit)
        password = "test123"
        hashed = hash_password(password)
        assert verify_password(password, hashed)
        assert not verify_password("wrong", hashed)
        print("  ✓ Password hashing works")

        # Test JWT creation
        token = create_access_token({"sub": "test-user-id"})
        assert len(token) > 20
        print("  ✓ JWT token creation works")

        return True
    except Exception as e:
        print(f"  ✗ Auth test failed: {e}")
        return False


def test_file_utils():
    """Test file utility functions."""
    print("\nTesting file utilities...")
    try:
        from backend.utils.file_utils import (
            compute_file_hash,
            generate_safe_filename,
            validate_file_extension,
            validate_mime_type,
        )

        # Test hash
        content = b"test content"
        hash_val = compute_file_hash(content)
        assert len(hash_val) == 64
        print("  ✓ File hashing works")

        # Test safe filename
        filename = generate_safe_filename("document.pdf")
        assert filename.endswith(".pdf")
        assert len(filename) > 10
        print("  ✓ Safe filename generation works")

        # Test extension validation
        assert validate_file_extension("test.pdf")
        assert validate_file_extension("test.jpg")
        assert not validate_file_extension("test.exe")
        print("  ✓ Extension validation works")

        # Test MIME validation
        pdf_content = b"%PDF-1.4"
        mime = validate_mime_type(pdf_content, "test.pdf")
        assert mime == "application/pdf"
        print("  ✓ MIME type validation works")

        return True
    except Exception as e:
        print(f"  ✗ File utils test failed: {e}")
        return False


def test_directories():
    """Test that required directories exist or can be created."""
    print("\nTesting directories...")
    try:
        required_dirs = [
            "data",
            "uploads",
            "uploads/originals",
            "uploads/processed",
            "logs",
            "reports",
        ]

        for dir_path in required_dirs:
            path = Path(dir_path)
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
            assert path.exists() and path.is_dir()

        print(f"  ✓ All {len(required_dirs)} directories ready")
        return True
    except Exception as e:
        print(f"  ✗ Directory test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("  GeoLedger System Test")
    print("=" * 60)
    print()

    tests = [
        ("Imports", test_imports),
        ("Directories", test_directories),
        ("Database", test_database),
        ("Authentication", test_auth),
        ("File Utilities", test_file_utils),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} test crashed: {e}")
            results.append((name, False))

    print("\n" + "=" * 60)
    print("  Test Results")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status} — {name}")

    print()
    print(f"  {passed}/{total} tests passed")
    print("=" * 60)

    if passed == total:
        print("\n✓ All tests passed! GeoLedger is ready.")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed. Check errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
