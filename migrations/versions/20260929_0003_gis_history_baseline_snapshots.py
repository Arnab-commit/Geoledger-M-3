"""Seed immutable baseline snapshots from existing parcel geometries."""

from uuid import uuid4
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "20260929_0003"
down_revision = "20260929_0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        """
        SELECT id, parcel_id, geojson, geometry_type, calculated_area, area_unit, source,
               source_document_id, source_page_number, confidence, verification_status,
               created_by, created_at
        FROM gis_geometries
        ORDER BY parcel_id, created_at NULLS FIRST, id
        """
    )).mappings().all()
    existing_geometry_ids = {
        row[0] for row in bind.execute(sa.text(
            "SELECT geometry_id FROM gis_geometry_versions WHERE geometry_id IS NOT NULL"
        )).all()
    }
    version_numbers = dict(bind.execute(sa.text(
        "SELECT parcel_id, max(version_number) FROM gis_geometry_versions GROUP BY parcel_id"
    )).all())
    snapshots = []
    for row in rows:
        if row["id"] in existing_geometry_ids:
            continue
        parcel_id = row["parcel_id"]
        version_numbers[parcel_id] = version_numbers.get(parcel_id, 0) + 1
        snapshots.append({
            "id": str(uuid4()),
            "parcel_id": parcel_id,
            "geometry_id": row["id"],
            "version_number": version_numbers[parcel_id],
            "event_type": "baseline",
            "geojson": row["geojson"],
            "geometry_type": row["geometry_type"],
            "calculated_area": row["calculated_area"],
            "area_unit": row["area_unit"],
            "source": row["source"],
            "source_document_id": row["source_document_id"],
            "source_page_number": row["source_page_number"],
            "confidence": row["confidence"],
            "verification_status": row["verification_status"] or "pending",
            "changed_by": row["created_by"],
            "reason": "Baseline snapshot of existing geometry; prior edit reason is unavailable.",
            "created_at": row["created_at"] or datetime.now(timezone.utc).replace(tzinfo=None),
            "is_deleted": False,
        })
    if snapshots:
        table = sa.table(
            "gis_geometry_versions",
            sa.column("id", sa.String()), sa.column("parcel_id", sa.String()),
            sa.column("geometry_id", sa.String()), sa.column("version_number", sa.Integer()),
            sa.column("event_type", sa.String()), sa.column("geojson", sa.Text()),
            sa.column("geometry_type", sa.String()), sa.column("calculated_area", sa.Float()),
            sa.column("area_unit", sa.String()), sa.column("source", sa.String()),
            sa.column("source_document_id", sa.String()), sa.column("source_page_number", sa.Integer()),
            sa.column("confidence", sa.Float()), sa.column("verification_status", sa.String()),
            sa.column("changed_by", sa.String()), sa.column("reason", sa.Text()),
            sa.column("created_at", sa.DateTime()), sa.column("is_deleted", sa.Boolean()),
        )
        op.bulk_insert(table, snapshots)


def downgrade():
    raise RuntimeError("Baseline GIS snapshots are audit history and must not be automatically deleted.")
