"""Copy an existing GeoLedger SQLite database to an empty PostgreSQL/PostGIS DB.

The SQLite source is opened read-only. All PostgreSQL data rows are inserted
inside one transaction; any failed insert or verification rolls back the full
data copy. The source database and external document files are never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import Enum as SAEnum
from sqlalchemy import MetaData, URL, create_engine, func, inspect, select, text

from backend.config import settings
from backend.database import Base, engine as destination_engine
from backend.models import all_models  # noqa: F401
from backend.models.gis import POSTGIS_TYPES_AVAILABLE, to_database_geometry
from backend.services.gis_service import extract_raw_geometry

BATCH_SIZE = 500
POSTGIS_EXTENSION_TABLES = {
    "spatial_ref_sys", "geometry_columns", "geography_columns",
    "raster_columns", "raster_overviews",
}


class RecordImportError(RuntimeError):
    """Sanitized row-failure report that never includes driver credentials."""


def _open_readonly_sqlite(path: Path):
    url = URL.create(
        "sqlite+pysqlite",
        database=f"file:{path.resolve().as_posix()}",
        query={"mode": "ro", "uri": "true"},
    )
    return create_engine(url)


def _normalize(value, is_enum=False):
    if is_enum and hasattr(value, "value") and hasattr(value, "name"):
        return ("enum", str(value.name).casefold())
    if is_enum and isinstance(value, str):
        return ("enum", value.casefold())
    if hasattr(value, "isoformat"):
        return ("datetime", value.isoformat())
    if isinstance(value, bytes):
        return ("bytes", value.hex())
    if isinstance(value, float):
        return ("float", format(value, ".17g"))
    if value is None:
        return None
    return ("scalar", value)


def _fingerprint(rows, columns, enum_columns):
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        values = [_normalize(row[column], column in enum_columns) for column in columns]
        digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def _preflight(source_engine, source_path: Path):
    metadata = MetaData()
    metadata.reflect(bind=source_engine)
    source_tables = set(metadata.tables)
    model_tables = set(Base.metadata.tables)
    if source_tables != model_tables:
        raise ValueError(
            f"SQLite table mismatch; missing from source={sorted(model_tables-source_tables)}, "
            f"not mapped for import={sorted(source_tables-model_tables)}"
        )

    report = {}
    with source_engine.connect() as conn:
        if conn.execute(text("PRAGMA quick_check")).scalar() != "ok":
            raise ValueError("SQLite quick_check failed")
        fk_errors = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
        if fk_errors:
            raise ValueError(f"SQLite has {len(fk_errors)} declared foreign-key violations")

        for name in sorted(source_tables):
            source_table = metadata.tables[name]
            model_table = Base.metadata.tables[name]
            source_columns = set(source_table.c.keys())
            model_columns = set(model_table.c.keys())
            unmapped = source_columns - model_columns
            if unmapped:
                raise ValueError(f"Table {name} has unmapped source columns: {sorted(unmapped)}")
            # Geometry is a deliberate additive PostGIS projection of the
            # authoritative GeoJSON column and does not exist in SQLite yet.
            missing = model_columns - source_columns
            allowed_missing = {"geometry"} if name == "gis_geometries" else set()
            unexpected_missing = missing - allowed_missing
            if unexpected_missing:
                raise ValueError(f"Table {name} lacks mapped source columns: {sorted(unexpected_missing)}")
            report[name] = conn.execute(select(func.count()).select_from(source_table)).scalar_one()

        geometries = []
        gis_table = metadata.tables["gis_geometries"]
        for row in conn.execute(select(gis_table.c.id, gis_table.c.crs, gis_table.c.geojson)):
            if str(row.crs).upper() not in ("EPSG:4326", "4326"):
                raise ValueError(f"GIS record {row.id} uses unsupported SRID/CRS {row.crs!r}; no reprojection is attempted")
            try:
                raw = extract_raw_geometry(json.loads(row.geojson))
                from shapely.geometry import shape
                shape(raw)
            except Exception as exc:
                raise ValueError(f"GIS record {row.id} has unreadable GeoJSON ({type(exc).__name__})") from exc
            geometries.append((row.id, raw))

        # This legacy link is intentionally not a constraint in the current
        # schema. Report existing broken links while preserving their rows.
        soft_orphans = conn.execute(text(
            "SELECT COUNT(*) FROM verification_cases v "
            "LEFT JOIN discrepancies d ON d.id = v.discrepancy_id "
            "WHERE v.discrepancy_id IS NOT NULL AND d.id IS NULL"
        )).scalar_one()

    return metadata, report, geometries, soft_orphans


def _ensure_empty_postgres():
    if destination_engine.dialect.name != "postgresql":
        raise ValueError("Set DATABASE_URL to a PostgreSQL URL using the psycopg driver")
    if not POSTGIS_TYPES_AVAILABLE:
        raise RuntimeError("Install the declared GeoAlchemy2 and psycopg dependencies first")

    expected = set(Base.metadata.tables)
    with destination_engine.connect() as conn:
        names_before = set(inspect(conn).get_table_names())
        managed_before = names_before - POSTGIS_EXTENSION_TABLES - {"alembic_version"}
        unexpected = managed_before - expected
        if unexpected:
            raise ValueError(f"Refusing import into a database with unrelated tables: {sorted(unexpected)}")
        if managed_before and managed_before != expected:
            raise ValueError("Refusing import into a partially initialized PostgreSQL schema")
        for name in managed_before:
            if conn.execute(select(func.count()).select_from(Base.metadata.tables[name])).scalar_one():
                raise ValueError(f"Refusing to import over non-empty PostgreSQL table: {name}")

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    with destination_engine.connect() as conn:
        names = set(inspect(conn).get_table_names()) - POSTGIS_EXTENSION_TABLES - {"alembic_version"}
        if names != expected:
            raise ValueError(f"PostgreSQL schema mismatch; missing={sorted(expected-names)}, unexpected={sorted(names-expected)}")
        populated = []
        for name in sorted(expected):
            if conn.execute(select(text("count(*)")).select_from(Base.metadata.tables[name])).scalar_one():
                populated.append(name)
        if populated:
            raise ValueError(f"Refusing to import over non-empty PostgreSQL tables: {populated}")


def _import_rows(source_engine, source_metadata, expected_counts, geometries):
    source_geometry = dict(geometries)
    with destination_engine.begin() as target:
        for source_table in Base.metadata.sorted_tables:
            name = source_table.name
            reflected = source_metadata.tables[name]
            insert_columns = [column.name for column in source_table.columns if column.name in reflected.c]
            if name == "gis_geometries":
                # geojson is authoritative; rebuild the derived geometry for
                # the target rather than importing a SQLite WKT projection.
                insert_columns = [column for column in insert_columns if column != "geometry"]
            source_statement = select(*(reflected.c[name] for name in insert_columns)).order_by(
                *(reflected.c[column.name] for column in source_table.primary_key.columns)
            )
            with source_engine.connect() as source:
                result = source.execution_options(stream_results=True).execute(source_statement)
                while batch := result.mappings().fetchmany(BATCH_SIZE):
                    payload = []
                    for row in batch:
                        values = {column: row[column] for column in insert_columns}
                        if name == "gis_geometries":
                            geom_id = values["id"]
                            geometry = source_geometry[geom_id]
                            values["geometry"] = to_database_geometry(geometry, target.dialect.name)
                        payload.append(values)
                    try:
                        target.execute(source_table.insert(), payload)
                    except Exception as exc:
                        primary_keys = [
                            str(item.get(column.name))
                            for item in payload
                            for column in source_table.primary_key.columns
                        ][:50]
                        raise RecordImportError(
                            f"Insert failed for {name}; affected source primary keys: {primary_keys}"
                        ) from exc
                result.close()
            actual = target.execute(select(text("count(*)")).select_from(source_table)).scalar_one()
            if actual != expected_counts[name]:
                raise ValueError(f"Count mismatch for {name}: source={expected_counts[name]} destination={actual}")

        # Compare a deterministic content fingerprint for every source column.
        for name in sorted(expected_counts):
            source_table = source_metadata.tables[name]
            target_table = Base.metadata.tables[name]
            columns = list(source_table.c.keys())
            if name == "gis_geometries":
                columns = [column for column in columns if column != "geometry"]
            pk_names = [column.name for column in source_table.primary_key.columns]
            source_query = select(*(source_table.c[column] for column in columns)).order_by(
                *(source_table.c[column] for column in pk_names)
            )
            target_query = select(*(target_table.c[column] for column in columns)).order_by(
                *(target_table.c[column] for column in pk_names)
            )
            with source_engine.connect() as source:
                source_rows = source.execute(source_query).mappings()
            enum_columns = {
                column.name for column in target_table.columns
                if isinstance(column.type, SAEnum) or hasattr(column.type, "enum_cls")
            }
            source_count, source_hash = _fingerprint(source_rows, columns, enum_columns)
            target_rows = target.execute(target_query).mappings()
            target_count, target_hash = _fingerprint(target_rows, columns, enum_columns)
            if source_count != target_count or source_hash != target_hash:
                raise ValueError(f"Content verification failed for table {name}")

        if expected_counts.get("documents", 0):
            source_documents = source_metadata.tables["documents"]
            src_hashes = None
            with source_engine.connect() as source:
                src_hashes = source.execute(
                    select(source_documents.c.id, source_documents.c.file_hash).order_by(source_documents.c.id)
                ).all()
            dst_hashes = target.execute(
                select(Base.metadata.tables["documents"].c.id, Base.metadata.tables["documents"].c.file_hash)
                .order_by(Base.metadata.tables["documents"].c.id)
            ).all()
            if src_hashes != dst_hashes:
                raise ValueError("Document SHA-256 values did not match after import")

        if target.dialect.name == "postgresql" and expected_counts.get("gis_geometries", 0):
            gis = Base.metadata.tables["gis_geometries"]
            wrong_srids = target.execute(
                select(func.count()).select_from(gis).where(
                    gis.c.geometry.is_(None) | (func.ST_SRID(gis.c.geometry) != 4326)
                )
            ).scalar_one()
            if wrong_srids:
                raise ValueError(f"{wrong_srids} imported parcel geometries have missing/wrong SRID")

        if target.dialect.name == "postgresql":
            target.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="SQLite database file (opened read-only)")
    parser.add_argument("--dry-run", action="store_true", help="Inspect source data only; do not connect to PostgreSQL")
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"SQLite source not found: {args.source}")

    source_engine = _open_readonly_sqlite(args.source)
    try:
        source_metadata, counts, geometries, orphan_count = _preflight(source_engine, args.source)
        print(f"SQLite source preflight passed: {len(counts)} tables, {sum(counts.values())} rows, {len(geometries)} GIS geometries")
        print("SQLite declared foreign-key violations: 0")
        if orphan_count:
            print(f"Existing verification_cases.discrepancy_id references without a matching discrepancy: {orphan_count} (preserved as-is)")
        for name, count in sorted(counts.items()):
            print(f"  {name}: {count}")
        if args.dry_run:
            print("Dry run only; no database was changed.")
            return 0
        if not settings.DATABASE_URL.startswith("postgresql+"):
            raise ValueError("DATABASE_URL must select PostgreSQL before importing")
        _ensure_empty_postgres()
        _import_rows(source_engine, source_metadata, counts, geometries)
        print("PostgreSQL import and transactional content verification passed.")
        return 0
    except Exception as exc:
        if isinstance(exc, RecordImportError):
            safe_detail = str(exc)
        else:
            safe_detail = type(exc).__name__
        print(
            f"Migration stopped ({safe_detail}); PostgreSQL row import was rolled back if it had begun. "
            "Review source data and PostgreSQL setup; sensitive connection details were not printed.",
            file=sys.stderr,
        )
        return 1
    finally:
        source_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
