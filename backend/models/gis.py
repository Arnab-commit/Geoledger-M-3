"""GIS geometry models."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Float, Text, ForeignKey, Index, Integer, Boolean, UniqueConstraint, cast
from sqlalchemy.types import UserDefinedType
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.sqltypes import NullType
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import relationship
from backend.database import Base

try:
    from geoalchemy2 import Geography
    POSTGIS_TYPES_AVAILABLE = True
except ImportError:  # Keep SQLite usable until optional DB dependencies are installed.
    Geography = None
    POSTGIS_TYPES_AVAILABLE = False


class _GeometryFromEWKT(FunctionElement):
    type = NullType()
    inherit_cache = True


@compiles(_GeometryFromEWKT, "postgresql")
def _compile_geometry_from_ewkt(element, compiler, **kwargs):
    value = compiler.process(element.clauses, **kwargs)
    return f"ST_GeomFromEWKT({value})"


@compiles(_GeometryFromEWKT, "sqlite")
def _compile_geometry_from_ewkt_sqlite(element, compiler, **kwargs):
    return compiler.process(element.clauses, **kwargs)


class SpatialGeometryType(UserDefinedType):
    """Use PostGIS geometry on PostgreSQL and ordinary WKT text on SQLite."""

    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "geometry(GEOMETRY,4326)"

    def bind_expression(self, bindvalue):
        return _GeometryFromEWKT(bindvalue)


@compiles(SpatialGeometryType, "sqlite")
def _compile_spatial_geometry_sqlite(type_, compiler, **kwargs):
    return "TEXT"


class GisGeometry(Base):
    __tablename__ = "gis_geometries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    geometry_type = Column(String(50), default="Polygon")
    geojson = Column(Text, nullable=False)
    # GeoJSON remains the stable API payload; this typed column supports
    # indexed PostGIS operations. SQLite stores WKT text in the same column.
    geometry = Column(SpatialGeometryType(), nullable=True)
    crs = Column(String(50), default="EPSG:4326")
    calculated_area = Column(Float, nullable=True)
    area_unit = Column(String(50), default="acres")
    source = Column(String(255), default="demo")
    is_authoritative = Column(String(10), default="false")
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    source_document_id = Column(String, ForeignKey("documents.id"), nullable=True)
    source_page_number = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    verification_status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    parcel = relationship("Parcel", back_populates="gis_geometries")

    def __repr__(self):
        return f"<GisGeometry parcel={self.parcel_id[:8]} ({self.source})>"


Index("ix_gis_geometries_parcel_id", GisGeometry.parcel_id)


class GisGeometryVersion(Base):
    """Immutable snapshots of geometry state changes, including deleted shapes."""

    __tablename__ = "gis_geometry_versions"
    __table_args__ = (UniqueConstraint("parcel_id", "version_number", name="uq_gis_geometry_versions_parcel_version"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    parcel_id = Column(String, ForeignKey("parcels.id"), nullable=False)
    geometry_id = Column(String, nullable=True)
    version_number = Column(Integer, nullable=False)
    event_type = Column(String(20), nullable=False)
    geojson = Column(Text, nullable=False)
    geometry_type = Column(String(50), nullable=True)
    calculated_area = Column(Float, nullable=True)
    area_unit = Column(String(50), nullable=True)
    source = Column(String(255), nullable=True)
    source_document_id = Column(String, nullable=True)
    source_page_number = Column(Integer, nullable=True)
    confidence = Column(Float, nullable=True)
    verification_status = Column(String(50), nullable=True)
    changed_by = Column(String, ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)


Index("ix_gis_geometry_versions_parcel_created", GisGeometryVersion.parcel_id, GisGeometryVersion.created_at)
if POSTGIS_TYPES_AVAILABLE:
    Index(
        "ix_gis_geometries_geometry_gist",
        GisGeometry.geometry,
        postgresql_using="gist",
    ).ddl_if(dialect="postgresql")
    Index(
        "ix_gis_geometries_geography_gist",
        cast(GisGeometry.geometry, Geography(srid=4326)),
        postgresql_using="gist",
    ).ddl_if(dialect="postgresql")


def to_database_geometry(geojson_geometry, dialect_name):
    """Build the stored geometry from existing GeoJSON without reprojection."""
    from shapely.geometry import shape

    parsed = shape(geojson_geometry)
    if dialect_name == "postgresql":
        if not POSTGIS_TYPES_AVAILABLE:
            raise RuntimeError("Install GeoAlchemy2 to use PostgreSQL/PostGIS.")
        return f"SRID=4326;{parsed.wkt}"
    return parsed.wkt
