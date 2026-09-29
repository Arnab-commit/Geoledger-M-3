"""Database connection and session management."""

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import settings


# SQLite-specific: enable WAL mode and foreign keys
is_sqlite = settings.DATABASE_URL.startswith("sqlite")
is_postgresql = settings.DATABASE_URL.startswith("postgresql+")
connect_args = {"check_same_thread": False} if is_sqlite else {}
engine_options = {"connect_args": connect_args, "echo": settings.DEBUG}
if is_postgresql:
    engine_options.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
        "pool_pre_ping": True,
    })

engine = create_engine(settings.DATABASE_URL, **engine_options)

# Enable SQLite foreign keys
if is_sqlite:
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_db_columns():
    """Apply additive legacy SQLite column updates; PostgreSQL uses Alembic."""
    if engine.dialect.name != "sqlite":
        return
    migrations = [
        ("users", "jurisdiction_scope", "VARCHAR(50) DEFAULT 'SCOPED'"),
        ("documents", "uploader_id", "VARCHAR(100)"),
        ("documents", "state", "VARCHAR(100)"),
        ("documents", "district", "VARCHAR(100)"),
        ("documents", "tehsil", "VARCHAR(100)"),
        ("documents", "village", "VARCHAR(100)"),
        ("extracted_fields", "ai_extracted_value", "TEXT"),
        ("extracted_fields", "officer_corrected_value", "TEXT"),
        ("extracted_fields", "corrected_by", "VARCHAR(100)"),
        ("extracted_fields", "corrected_at", "DATETIME"),
        ("extracted_fields", "correction_reason", "TEXT"),
        ("extracted_fields", "final_verified_value", "TEXT"),
        ("extracted_fields", "verified_by", "VARCHAR(100)"),
        ("extracted_fields", "verified_at", "DATETIME"),
        ("verification_cases", "submitted_by", "VARCHAR(100)"),
        ("verification_cases", "assigned_officer_id", "VARCHAR(100)"),
        ("verification_cases", "state", "VARCHAR(100)"),
        ("verification_cases", "district", "VARCHAR(100)"),
        ("verification_cases", "tehsil", "VARCHAR(100)"),
        ("verification_cases", "village", "VARCHAR(100)"),
        ("verification_cases", "assigned_officer_id", "VARCHAR(100)"),
        ("verification_actions", "reason", "TEXT"),
        ("audit_logs", "actor_role", "VARCHAR(50)"),
        ("audit_logs", "result", "VARCHAR(20) DEFAULT 'SUCCESS'"),
        ("audit_logs", "reason", "TEXT"),
        ("audit_logs", "correlation_id", "VARCHAR(100)"),
        ("gis_geometries", "geometry", "TEXT"),
        ("gis_geometries", "created_by", "VARCHAR(100)"),
        ("gis_geometries", "source_document_id", "VARCHAR(100)"),
        ("gis_geometries", "source_page_number", "INTEGER"),
        ("gis_geometries", "confidence", "REAL"),
        ("gis_geometries", "verification_status", "VARCHAR(50) DEFAULT 'pending'"),
    ]

    with engine.connect() as conn:
        for table, col, col_def in migrations:
            try:
                res = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                cols = [r[1] for r in res]
                if cols and col not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                    conn.commit()
            except Exception as exc:
                raise RuntimeError(
                    f"SQLite schema update failed for {table}.{col}; "
                    "the existing database was not intentionally reset."
                ) from exc


def init_db():
    """Initialize SQLite locally or validate an Alembic-managed PostGIS schema."""
    from backend.models import all_models  # noqa: F401 — triggers model registration
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
        migrate_db_columns()
        for table in Base.metadata.tables.values():
            for index in table.indexes:
                index.create(bind=engine, checkfirst=True)
        return
    if engine.dialect.name != "postgresql":
        raise RuntimeError("GeoLedger supports SQLite and PostgreSQL database URLs only.")
    from backend.models.gis import POSTGIS_TYPES_AVAILABLE
    if not POSTGIS_TYPES_AVAILABLE:
        raise RuntimeError("Install the declared GeoAlchemy2 dependency to use PostgreSQL/PostGIS.")

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT postgis_full_version()"))
            existing = set(inspect(conn).get_table_names())
            missing = set(Base.metadata.tables) - existing
            if missing:
                raise RuntimeError(
                    "PostgreSQL schema is not initialized. Run `alembic upgrade head`; "
                    f"missing tables: {', '.join(sorted(missing))}."
                )
            if "alembic_version" not in existing:
                raise RuntimeError("PostgreSQL schema has no Alembic revision; run `alembic upgrade head`.")
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            if version is None:
                raise RuntimeError("PostgreSQL schema has no Alembic revision; run `alembic upgrade head`.")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL/PostGIS could not be validated. Check the configured database "
            "and ensure the PostGIS extension is installed."
        ) from exc
