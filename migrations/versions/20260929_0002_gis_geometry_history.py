"""Additive GIS geometry provenance and immutable version history."""

from alembic import op
import sqlalchemy as sa

revision = "20260929_0002"
down_revision = "20260929_0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("gis_geometries")}
    column_specs = [
        ("created_by", sa.String(), "fk_gis_geometries_created_by_users", "users"),
        ("source_document_id", sa.String(), "fk_gis_geometries_source_document_documents", "documents"),
        ("source_page_number", sa.Integer(), None, None),
        ("confidence", sa.Float(), None, None),
        ("verification_status", sa.String(length=50), None, None),
    ]
    for name, type_, constraint, target in column_specs:
        if name not in existing_columns:
            kwargs = {"server_default": "pending"} if name == "verification_status" else {}
            op.add_column("gis_geometries", sa.Column(name, type_, nullable=True, **kwargs))
            if constraint:
                op.create_foreign_key(constraint, "gis_geometries", target, [name], ["id"])

    if "gis_geometry_versions" not in inspector.get_table_names():
        op.create_table(
            "gis_geometry_versions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("parcel_id", sa.String(), nullable=False),
            sa.Column("geometry_id", sa.String(), nullable=True),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=20), nullable=False),
            sa.Column("geojson", sa.Text(), nullable=False),
            sa.Column("geometry_type", sa.String(length=50), nullable=True),
            sa.Column("calculated_area", sa.Float(), nullable=True),
            sa.Column("area_unit", sa.String(length=50), nullable=True),
            sa.Column("source", sa.String(length=255), nullable=True),
            sa.Column("source_document_id", sa.String(), nullable=True),
            sa.Column("source_page_number", sa.Integer(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("verification_status", sa.String(length=50), nullable=True),
            sa.Column("changed_by", sa.String(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["parcel_id"], ["parcels.id"], name="fk_gis_geometry_versions_parcel"),
            sa.ForeignKeyConstraint(["changed_by"], ["users.id"], name="fk_gis_geometry_versions_changed_by"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("parcel_id", "version_number", name="uq_gis_geometry_versions_parcel_version"),
        )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("gis_geometry_versions")}
    if "ix_gis_geometry_versions_parcel_created" not in indexes:
        op.create_index(
            "ix_gis_geometry_versions_parcel_created", "gis_geometry_versions",
            ["parcel_id", "created_at"], unique=False,
        )


def downgrade():
    raise RuntimeError("GIS history may be required for audit; restore from a verified backup instead of dropping it.")
