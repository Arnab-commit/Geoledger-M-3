"""Initial PostgreSQL + PostGIS schema baseline for GeoLedger."""

from alembic import op

from backend.database import Base
from backend.models import all_models  # noqa: F401

revision = "20260929_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # PostGIS is required before SQLAlchemy creates the geometry column.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    # A schema drop would destroy migrated land records; use a verified backup
    # and a separately reviewed recovery plan instead of automated downgrade.
    raise RuntimeError("GeoLedger's baseline migration is intentionally non-destructive.")
