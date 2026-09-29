"""GIS API endpoints for spatial operations, parcel geometry management, and cadastral validation."""

import logging
import json
from typing import Dict, Any, Optional, List, Union, Literal
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, aliased
from sqlalchemy import cast, func
from pydantic import BaseModel, Field, model_validator

try:
    from geoalchemy2 import Geography
except ImportError:  # SQLite remains usable without the PostgreSQL extras.
    Geography = None

from backend.database import get_db
from backend.api.auth import get_current_user
from backend.models.user import User
from backend.models.parcel import Parcel, ParcelIdentifier, ParcelDocument
from backend.models.document import Document
from backend.models.ownership import Owner
from backend.models.gis import GisGeometry, GisGeometryVersion
from backend.models.gis import POSTGIS_TYPES_AVAILABLE, to_database_geometry
from backend.models.discrepancy import Discrepancy, DiscrepancyType, Severity
from backend.models.verification import VerificationCase, VerificationStatus
from backend.models.audit import AuditLog
from backend.services.gis_service import (
    calculate_area_from_geojson,
    compare_areas,
    validate_geometry,
    extract_raw_geometry,
    area_to_acres,
)

from backend.security.permissions import (
    GIS_READ_OWN,
    GIS_READ_SCOPED,
    GIS_READ_ALL,
    GIS_EDIT,
    GIS_APPROVE_GEOMETRY,
)
from backend.security.jurisdiction import filter_parcels_by_scope
from backend.security.authorization import require_permission, authorize_parcel_access, log_security_event
from backend.security.permissions import user_has_permission

logger = logging.getLogger("geoldger.api.gis")

router = APIRouter(prefix="/api/gis", tags=["GIS"])


class GeoJsonGeometryRequest(BaseModel):
    geojson: Optional[Dict[str, Any]] = None
    geometry: Optional[Dict[str, Any]] = None
    source: Optional[str] = "user_drawn"
    is_authoritative: Optional[Union[bool, str]] = "false"
    notes: Optional[str] = None
    source_document_id: Optional[str] = None
    source_page_number: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_source_page_reference(self):
        if self.source_page_number is not None and not self.source_document_id:
            raise ValueError("source_document_id is required when source_page_number is provided")
        return self


class AreaCalculationRequest(BaseModel):
    geojson: Optional[Dict[str, Any]] = None
    geometry: Optional[Dict[str, Any]] = None
    use_projected: Optional[bool] = True
    state: Optional[str] = None


class SpatialQueryRequest(BaseModel):
    geometry: Dict[str, Any]
    operation: Literal["intersects", "overlaps", "contains", "within", "touches", "nearby"]
    distance_meters: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_distance(self):
        if self.operation == "nearby" and self.distance_meters is None:
            raise ValueError("distance_meters is required for nearby queries")
        return self


@router.get("/parcels")
async def get_all_parcel_geometries(
    village: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None, min_length=1, max_length=200),
    min_lon: Optional[float] = Query(None, ge=-180, le=180),
    min_lat: Optional[float] = Query(None, ge=-90, le=90),
    max_lon: Optional[float] = Query(None, ge=-180, le=180),
    max_lat: Optional[float] = Query(None, ge=-90, le=90),
    limit: int = Query(1000, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get GeoJSON FeatureCollection of all parcels with saved GIS geometries.
    Scoped by user role and authorized jurisdiction.
    """
    # Base parcel query scoped by user permissions
    parcel_query = db.query(Parcel)
    if village:
        parcel_query = parcel_query.filter(Parcel.village.ilike(f"%{village}%"))
    if district:
        parcel_query = parcel_query.filter(Parcel.district.ilike(f"%{district}%"))
    if status:
        parcel_query = parcel_query.filter(Parcel.verification_status == status)
    if search:
        like = f"%{search.strip()}%"
        parcel_query = parcel_query.filter(
            (Parcel.parcel_code.ilike(like)) | (Parcel.ulpin.ilike(like)) |
            (Parcel.current_owner.ilike(like)) | (Parcel.village.ilike(like)) |
            (Parcel.tehsil.ilike(like)) | (Parcel.district.ilike(like)) |
            Parcel.identifiers.any(ParcelIdentifier.identifier_value.ilike(like))
        )

    scoped_parcel_ids = filter_parcels_by_scope(parcel_query, current_user, db).with_entities(Parcel.id).statement

    latest_candidate = aliased(GisGeometry)
    latest_geometry_id = (
        db.query(latest_candidate.id)
        .filter(latest_candidate.parcel_id == GisGeometry.parcel_id)
        .order_by(latest_candidate.updated_at.desc(), latest_candidate.id.desc())
        .limit(1)
        .correlate(GisGeometry)
        .scalar_subquery()
    )
    query = db.query(GisGeometry).options(joinedload(GisGeometry.parcel)).filter(
        GisGeometry.parcel_id.in_(scoped_parcel_ids), GisGeometry.id == latest_geometry_id
    )
    viewport_values = (min_lon, min_lat, max_lon, max_lat)
    if any(value is not None for value in viewport_values):
        if any(value is None for value in viewport_values) or min_lon >= max_lon or min_lat >= max_lat:
            raise HTTPException(status_code=400, detail="A valid complete map viewport is required")
        if db.bind.dialect.name == "postgresql":
            viewport = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
            query = query.filter(GisGeometry.geometry.op("&&")(viewport))
    query = query.order_by(GisGeometry.updated_at.desc())
    # Bound database work even when the caller requests a broad map extent.
    gis_records = query.limit(limit).offset(offset).all()

    parcel_ids = list({record.parcel_id for record in gis_records})
    identifiers_by_parcel: Dict[str, Dict[str, str]] = {}
    for identifier in db.query(ParcelIdentifier).filter(ParcelIdentifier.parcel_id.in_(parcel_ids)).all() if parcel_ids else []:
        identifiers_by_parcel.setdefault(identifier.parcel_id, {})[identifier.identifier_type] = identifier.identifier_value
    owners_by_parcel: Dict[str, List[Owner]] = {}
    for owner in db.query(Owner).filter(Owner.parcel_id.in_(parcel_ids)).all() if parcel_ids else []:
        owners_by_parcel.setdefault(owner.parcel_id, []).append(owner)
    discrepancies_by_parcel = {
        record.parcel_id
        for record in db.query(Discrepancy.parcel_id).filter(
            Discrepancy.parcel_id.in_(parcel_ids),
            Discrepancy.discrepancy_type.in_([DiscrepancyType.GIS_AREA_CONFLICT, DiscrepancyType.BOUNDARY_CONFLICT]),
            Discrepancy.resolution_status == "open",
        ).all()
    } if parcel_ids else set()

    features = []
    seen_parcels = set()

    for rec in gis_records:
        parcel = rec.parcel
        if not parcel or parcel.id in seen_parcels:
            continue

        try:
            raw_geom = extract_raw_geometry(rec.geojson)
        except Exception as e:
            logger.warning(f"Could not parse stored GeoJSON for GIS record {rec.id}: {e}")
            continue

        # Gather identifiers
        id_map = identifiers_by_parcel.get(parcel.id, {})

        # Gather owners
        owners = owners_by_parcel.get(parcel.id, [])
        primary_owner = parcel.current_owner or (owners[0].name if owners else None)
        co_owners_list = [o.name for o in owners if o.name != primary_owner]
        father_name = owners[0].father_husband_name if owners else None

        # Calculate / get area comparison
        doc_area = parcel.current_area
        comparable_area_acres = area_to_acres(doc_area, parcel.area_unit)
        gis_area = rec.calculated_area

        validation_status = "UNCHECKED"
        variance_pct = 0.0
        variance_acres = 0.0
        severity = "INFO"

        if comparable_area_acres is not None and gis_area is not None:
            comp = compare_areas(comparable_area_acres, gis_area, tolerance=0.10)
            validation_status = comp["status"]
            variance_pct = comp["variance_percent"]
            variance_acres = comp["variance_acres"]
            severity = comp["severity"]

        # Check for open discrepancies
        feature = {
            "type": "Feature",
            "id": rec.id,
            "geometry": raw_geom,
            "properties": {
                "gis_id": rec.id,
                "parcel_id": parcel.id,
                "parcel_code": parcel.parcel_code,
                "ulpin": parcel.ulpin,
                "survey_number": id_map.get("survey_no") or id_map.get("plot_no") or id_map.get("khasra_no") or parcel.parcel_code,
                "khasra_number": id_map.get("khasra_no"),
                "plot_number": id_map.get("plot_no"),
                "khata_number": id_map.get("khata_no") or id_map.get("khatian_no"),
                "owner_name": primary_owner or "Owner information not available.",
                "co_owners": co_owners_list,
                "father_husband_name": father_name,
                "village": parcel.village or "Unspecified",
                "mouza": parcel.mouza or parcel.village or "Unspecified",
                "tehsil": parcel.tehsil or "Unspecified",
                "district": parcel.district or "Unspecified",
                "state": parcel.state or "Unspecified",
                "recorded_area": doc_area,
                "calculated_area": gis_area,
                "area_unit": parcel.area_unit or rec.area_unit or "acres",
                "land_classification": parcel.land_classification or "Standard Agricultural",
                "validation_status": validation_status,
                "variance_percent": variance_pct,
                "variance_acres": variance_acres,
                "severity": severity,
                "has_discrepancy": parcel.id in discrepancies_by_parcel,
                "parcel_verification_status": parcel.verification_status,
                "geometry_verification_status": rec.verification_status,
                "source": rec.source or "user_drawn",
                "is_authoritative": rec.is_authoritative == "true",
                "created_at": rec.created_at.isoformat() if rec.created_at else None,
                "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
            }
        }
        features.append(feature)
        seen_parcels.add(parcel.id)

    logger.info(f"Retrieved {len(features)} parcel geometries for GIS map")
    return {
        "type": "FeatureCollection",
        "features": features,
        "total_features": len(features),
        "limit": limit,
        "offset": offset,
    }


@router.get("/parcels/{parcel_id}")
async def get_parcel_gis_details(
    parcel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get full GIS & Digital Twin spatial record for a specific parcel.
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    authorize_parcel_access(parcel, current_user, "read", db)

    # Identifiers
    identifiers = db.query(ParcelIdentifier).filter(ParcelIdentifier.parcel_id == parcel.id).all()
    id_dict = {i.identifier_type: i.identifier_value for i in identifiers}

    # Owners
    owners = db.query(Owner).filter(Owner.parcel_id == parcel.id).all()
    primary_owner = parcel.current_owner or (owners[0].name if owners else None)
    co_owners = [o.name for o in owners if o.name != primary_owner]

    # Geometries
    geometries = db.query(GisGeometry).filter(GisGeometry.parcel_id == parcel.id).order_by(GisGeometry.updated_at.desc()).all()

    active_geom = None
    geom_list = []
    for g in geometries:
        try:
            raw = extract_raw_geometry(g.geojson)
            item = {
                "id": g.id,
                "geometry": raw,
                "geometry_type": g.geometry_type,
                "crs": g.crs,
                "geometry_valid": validate_geometry(raw)["valid"],
                "calculated_area": g.calculated_area,
                "area_unit": g.area_unit,
                "source": g.source,
                "is_authoritative": g.is_authoritative == "true",
                "created_by": g.created_by,
                "source_document_id": g.source_document_id,
                "source_page_number": g.source_page_number,
                "confidence": g.confidence,
                "verification_status": g.verification_status,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            }
            geom_list.append(item)
            if active_geom is None:
                active_geom = item
        except Exception as e:
            logger.warning(f"Error parsing geometry {g.id}: {e}")

    # Area validation
    area_validation = None
    comparable_area_acres = area_to_acres(parcel.current_area, parcel.area_unit)
    if comparable_area_acres is not None and active_geom and active_geom.get("calculated_area") is not None:
        area_validation = compare_areas(comparable_area_acres, active_geom["calculated_area"], tolerance=0.10)

    # Discrepancies
    discrepancies = db.query(Discrepancy).filter(
        Discrepancy.parcel_id == parcel.id,
        Discrepancy.discrepancy_type.in_([DiscrepancyType.GIS_AREA_CONFLICT, DiscrepancyType.BOUNDARY_CONFLICT])
    ).all()
    verification_cases = db.query(VerificationCase).filter(
        VerificationCase.parcel_id == parcel.id
    ).order_by(VerificationCase.created_at.desc()).limit(20).all()

    # Audit history
    audit_events = db.query(AuditLog).filter(
        AuditLog.entity_type == "GisGeometry",
        AuditLog.details.ilike(f"%{parcel.parcel_code}%") | (AuditLog.entity_id.in_([g.id for g in geometries]))
    ).order_by(AuditLog.created_at.desc()).limit(10).all()

    return {
        "parcel": {
            "id": parcel.id,
            "parcel_code": parcel.parcel_code,
            "ulpin": parcel.ulpin,
            "village": parcel.village,
            "mouza": parcel.mouza,
            "tehsil": parcel.tehsil,
            "district": parcel.district,
            "state": parcel.state,
            "current_area": parcel.current_area,
            "area_unit": parcel.area_unit,
            "land_classification": parcel.land_classification,
            "current_owner": primary_owner or "Owner information not available.",
            "co_owners": co_owners,
            "father_husband_name": owners[0].father_husband_name if owners else None,
            "identifiers": id_dict,
            "verification_status": parcel.verification_status,
        },
        "active_geometry": active_geom,
        "all_geometries": geom_list,
        "area_validation": area_validation,
        "area_validation_note": None if area_validation or parcel.current_area is None else "Recorded area unit is not recognized for automatic comparison; values are shown without a match decision.",
        "discrepancies": [
            {
                "id": d.id,
                "type": d.discrepancy_type.value,
                "severity": d.severity.value,
                "reason": d.reason,
                "status": d.resolution_status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in discrepancies
        ],
        "linked_documents": _visible_parcel_documents(db, parcel, current_user),
        "verification_cases": [
            {
                "id": case.id,
                "case_type": case.case_type,
                "status": case.status.value if hasattr(case.status, "value") else str(case.status),
                "summary": case.summary,
                "created_at": case.created_at.isoformat() if case.created_at else None,
            }
            for case in verification_cases
        ],
        "audit_history": [
            {
                "id": a.id,
                "action": a.action,
                "details": a.details,
                "user_id": a.user_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in audit_events
        ]
    }


def _visible_parcel_documents(db: Session, parcel: Parcel, current_user: User) -> List[Dict[str, Any]]:
    """Return only documents the caller is independently allowed to read."""
    from backend.security.authorization import authorize_document_access

    result = []
    rows = (
        db.query(Document, ParcelDocument)
        .join(ParcelDocument, ParcelDocument.document_id == Document.id)
        .filter(ParcelDocument.parcel_id == parcel.id)
        .order_by(Document.upload_timestamp.desc())
        .limit(100)
        .all()
    )
    for doc, link in rows:
        try:
            authorize_document_access(doc, current_user, "read", db)
        except HTTPException:
            continue
        result.append({
            "id": doc.id,
            "filename": doc.original_filename,
            "document_type": doc.document_type.value if hasattr(doc.document_type, "value") else str(doc.document_type),
            "upload_timestamp": doc.upload_timestamp.isoformat() if doc.upload_timestamp else None,
            "relationship_type": link.relationship_type,
        })
    return result


@router.post("/parcels/{parcel_id}/geometry")
async def save_or_update_parcel_geometry(
    parcel_id: str,
    data: GeoJsonGeometryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(GIS_EDIT)),
):
    """
    Create or edit parcel polygon geometry on the map.
    Validates topology, calculates projected UTM geodesic area, creates audit logs,
    and updates GIS discrepancy records if area variance exceeds tolerance.
    Enforces GIS_EDIT permission and parcel jurisdiction scoping.
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).with_for_update().first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    # Strict jurisdiction / ownership authorization
    authorize_parcel_access(parcel, current_user, "edit_geometry", db)

    try:
        input_geom = data.geojson or data.geometry
        if not input_geom:
            raise HTTPException(status_code=400, detail="Missing geometry data in request payload.")
        raw_geom = extract_raw_geometry(input_geom)
        authoritative = str(data.is_authoritative).strip().lower() in ("true", "1", "yes")
        if authoritative and not user_has_permission(current_user, GIS_APPROVE_GEOMETRY):
            raise HTTPException(status_code=403, detail="Administrative approval is required for authoritative geometry")
        validation = validate_geometry(raw_geom)

        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid geometry: {'; '.join(validation['issues'])}"
            )

        # Calculate projected UTM area
        area_acres, unit, area_sqm = calculate_area_from_geojson(raw_geom, use_projected=True)

        # Check existing geometry for this parcel
        existing_geom = db.query(GisGeometry).filter(
            GisGeometry.parcel_id == parcel.id,
            GisGeometry.is_authoritative == "false"
        ).order_by(GisGeometry.updated_at.desc()).first()

        old_area = existing_geom.calculated_area if existing_geom else None
        action_name = "UPDATE_PARCEL_GEOMETRY" if existing_geom else "CREATE_PARCEL_GEOMETRY"

        if data.source_document_id:
            linked_source = db.query(ParcelDocument).filter(
                ParcelDocument.parcel_id == parcel.id,
                ParcelDocument.document_id == data.source_document_id,
            ).first()
            if not linked_source:
                raise HTTPException(status_code=400, detail="Source document must already be linked to this parcel")

        if existing_geom:
            existing_geom.geojson = json.dumps(raw_geom)
            existing_geom.geometry = to_database_geometry(raw_geom, db.bind.dialect.name)
            existing_geom.geometry_type = validation["geometry_type"]
            existing_geom.calculated_area = area_acres
            existing_geom.area_unit = unit
            existing_geom.source = data.source or "user_edited"
            existing_geom.updated_at = datetime.now(timezone.utc)
            existing_geom.created_by = current_user.id
            existing_geom.source_document_id = data.source_document_id
            existing_geom.source_page_number = data.source_page_number
            existing_geom.verification_status = "pending"
            gis_record = existing_geom
        else:
            gis_record = GisGeometry(
                parcel_id=parcel.id,
                geojson=json.dumps(raw_geom),
                geometry=to_database_geometry(raw_geom, db.bind.dialect.name),
                geometry_type=validation["geometry_type"],
                calculated_area=area_acres,
                area_unit=unit,
                source=data.source or "user_drawn",
                is_authoritative="true" if authoritative else "false",
                created_by=current_user.id,
                source_document_id=data.source_document_id,
                source_page_number=data.source_page_number,
                verification_status="verified" if authoritative else "pending",
            )
            db.add(gis_record)

        db.flush()

        prior_versions = db.query(func.max(GisGeometryVersion.version_number)).filter(
            GisGeometryVersion.parcel_id == parcel.id
        ).scalar()
        db.add(GisGeometryVersion(
            parcel_id=parcel.id,
            geometry_id=gis_record.id,
            version_number=(prior_versions or 0) + 1,
            event_type="updated" if existing_geom else "created",
            geojson=json.dumps(raw_geom),
            geometry_type=validation["geometry_type"],
            calculated_area=area_acres,
            area_unit=unit,
            source=gis_record.source,
            source_document_id=gis_record.source_document_id,
            source_page_number=gis_record.source_page_number,
            confidence=gis_record.confidence,
            verification_status=gis_record.verification_status,
            changed_by=current_user.id,
            reason=data.notes,
        ))

        overlap_parcels_count = 0
        if db.bind.dialect.name == "postgresql":
            candidate_geometry = func.ST_SetSRID(
                func.ST_GeomFromGeoJSON(json.dumps(raw_geom, separators=(",", ":"))), 4326
            )
            overlap_parcels_count = (
                db.query(GisGeometry.parcel_id)
                .filter(
                    GisGeometry.parcel_id != parcel.id,
                    GisGeometry.geometry.isnot(None),
                    func.ST_Overlaps(GisGeometry.geometry, candidate_geometry),
                )
                .distinct()
                .limit(21)
                .count()
            )
            if overlap_parcels_count:
                boundary_disc = db.query(Discrepancy).filter(
                    Discrepancy.parcel_id == parcel.id,
                    Discrepancy.discrepancy_type == DiscrepancyType.BOUNDARY_CONFLICT,
                    Discrepancy.resolution_status == "open",
                ).first()
                if not boundary_disc:
                    boundary_disc = Discrepancy(
                        parcel_id=parcel.id,
                        discrepancy_type=DiscrepancyType.BOUNDARY_CONFLICT,
                        severity=Severity.MEDIUM,
                        field_name="geometry_overlap",
                        value_a=parcel.parcel_code,
                        value_b=f"{min(overlap_parcels_count, 21)} overlapping parcel geometries",
                        reason="PostGIS detected an area overlap with another parcel boundary. This is a review flag and does not establish fraud or legal boundary status.",
                        resolution_status="open",
                    )
                    db.add(boundary_disc)
                pending_overlap_case = db.query(VerificationCase).filter(
                    VerificationCase.parcel_id == parcel.id,
                    VerificationCase.case_type == "gis_geometry_overlap",
                    VerificationCase.status == VerificationStatus.PENDING,
                ).first()
                if not pending_overlap_case:
                    db.add(VerificationCase(
                        parcel_id=parcel.id,
                        case_type="gis_geometry_overlap",
                        priority="medium",
                        status=VerificationStatus.PENDING,
                        summary=f"Potential spatial overlap detected for parcel {parcel.parcel_code}; officer review required.",
                    ))

        # Spatial comparison against deed recorded area
        comparison = None
        discrepancy_record = None

        comparable_area_acres = area_to_acres(parcel.current_area, parcel.area_unit)
        if comparable_area_acres is not None:
            comparison = compare_areas(comparable_area_acres, area_acres, tolerance=0.10)

            # Look for existing GIS area discrepancy
            existing_disc = db.query(Discrepancy).filter(
                Discrepancy.parcel_id == parcel.id,
                Discrepancy.discrepancy_type == DiscrepancyType.GIS_AREA_CONFLICT,
            ).first()

            if not comparison["within_tolerance"]:
                # Area mismatch detected (> 10%)
                sev = Severity.HIGH if comparison["variance_percent"] > 25 else Severity.MEDIUM
                reason_text = (
                    f"GIS geodesic area ({area_acres:.4f} acres) differs from recorded deed area "
                    f"({comparable_area_acres:.4f} acres) by {comparison['variance_percent']:.1f}% "
                    f"({comparison['variance_acres']:.4f} acres deviation). Computed via UTM {validation.get('utm_zone', 'Projection')}."
                )

                if existing_disc:
                    existing_disc.value_a = f"{comparable_area_acres:.4f} acres (Recorded Deed)"
                    existing_disc.value_b = f"{area_acres:.4f} acres (GIS Cadastral Polygon)"
                    existing_disc.similarity_score = round(max(0.0, 1.0 - (comparison["variance_acres"] / comparable_area_acres)), 2)
                    existing_disc.reason = reason_text
                    existing_disc.severity = sev
                    existing_disc.resolution_status = "open"
                    discrepancy_record = existing_disc
                else:
                    discrepancy_record = Discrepancy(
                        parcel_id=parcel.id,
                        discrepancy_type=DiscrepancyType.GIS_AREA_CONFLICT,
                        severity=sev,
                        field_name="area",
                        value_a=f"{comparable_area_acres:.4f} acres (Recorded Deed)",
                        value_b=f"{area_acres:.4f} acres (GIS Cadastral Polygon)",
                        similarity_score=round(max(0.0, 1.0 - (comparison["variance_acres"] / comparable_area_acres)), 2),
                        reason=reason_text,
                        resolution_status="open",
                    )
                    db.add(discrepancy_record)
                    db.flush()

                # Also create / ensure verification case is open for human officer
                existing_case = db.query(VerificationCase).filter(
                    VerificationCase.parcel_id == parcel.id,
                    VerificationCase.case_type == "gis_area_mismatch",
                    VerificationCase.status == VerificationStatus.PENDING
                ).first()

                if not existing_case:
                    v_case = VerificationCase(
                        parcel_id=parcel.id,
                        discrepancy_id=discrepancy_record.id if discrepancy_record else None,
                        case_type="gis_area_mismatch",
                        priority="high" if comparison["variance_percent"] > 25 else "medium",
                        status=VerificationStatus.PENDING,
                        summary=f"Spatial Area Variance: {comparison['variance_percent']:.1f}% for parcel {parcel.parcel_code}",
                    )
                    db.add(v_case)

            else:
                # Within tolerance - resolve any existing area conflict
                if existing_disc and existing_disc.resolution_status == "open":
                    existing_disc.resolution_status = "resolved"
                    existing_disc.resolved_by = current_user.username or current_user.email
                    existing_disc.resolved_at = datetime.now(timezone.utc)
                    existing_disc.resolution_notes = f"Resolved automatically: Updated GIS polygon matches recorded area within tolerance ({comparison['variance_percent']:.2f}%)."

        # Record Audit Log
        audit_details = json.dumps({
            "parcel_id": parcel.id,
            "parcel_code": parcel.parcel_code,
            "gis_id": gis_record.id,
            "action": action_name,
            "calculated_area_acres": area_acres,
            "calculated_area_sqm": area_sqm,
            "old_area_acres": old_area,
            "source": data.source or "user_drawn",
            "user": current_user.username or current_user.email,
            "notes": data.notes,
        })

        audit_entry = AuditLog(
            user_id=current_user.id,
            action=action_name,
            entity_type="GisGeometry",
            entity_id=gis_record.id,
            old_value=str(old_area) if old_area is not None else None,
            new_value=str(area_acres),
            details=audit_details,
        )
        db.add(audit_entry)

        db.commit()

        logger.info(f"Saved GIS geometry for parcel {parcel.parcel_code}: {area_acres:.4f} acres ({action_name})")

        return {
            "status": "success",
            "message": "Parcel geometry saved successfully",
            "parcel_id": parcel.id,
            "parcel_code": parcel.parcel_code,
            "gis_id": gis_record.id,
            "calculated_area_acres": area_acres,
            "calculated_area_sqm": area_sqm,
            "area_unit": unit,
            "comparison": comparison,
            "validation": validation,
            "discrepancy_created": discrepancy_record is not None and not (comparison and comparison.get("within_tolerance")),
            "overlap_parcels_count": overlap_parcels_count,
            "audit_id": audit_entry.id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save parcel geometry: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to save geometry")


@router.delete("/parcels/{parcel_id}/geometry")
async def delete_active_parcel_geometry(
    parcel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(GIS_EDIT)),
):
    """Delete the active user-drawn geometry for a parcel."""
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    authorize_parcel_access(parcel, current_user, "edit_geometry", db)

    geom = db.query(GisGeometry).filter(
        GisGeometry.parcel_id == parcel.id,
        GisGeometry.is_authoritative == "false"
    ).order_by(GisGeometry.updated_at.desc()).first()

    if not geom:
        if user_has_permission(current_user, GIS_APPROVE_GEOMETRY):
            geom = db.query(GisGeometry).filter(GisGeometry.parcel_id == parcel.id).first()
        if not geom:
            raise HTTPException(status_code=404, detail="No active geometry found for this parcel")

    return await delete_parcel_geometry(parcel_id=parcel.id, geometry_id=geom.id, db=db, current_user=current_user)


@router.delete("/parcels/{parcel_id}/geometry/{geometry_id}")
async def delete_parcel_geometry(
    parcel_id: str,
    geometry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission(GIS_EDIT)),
):
    """
    Delete a user-drawn or edited geometry for a parcel.
    Authoritative cadastral geometries cannot be deleted without administrative override.
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).with_for_update().first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    authorize_parcel_access(parcel, current_user, "edit_geometry", db)

    geom = db.query(GisGeometry).filter(
        GisGeometry.id == geometry_id,
        GisGeometry.parcel_id == parcel.id
    ).first()

    if not geom:
        raise HTTPException(status_code=404, detail="Geometry record not found for this parcel")

    if geom.is_authoritative == "true" and not user_has_permission(current_user, GIS_APPROVE_GEOMETRY):
        raise HTTPException(status_code=403, detail="Cannot delete authoritative cadastral geometry without administrative role")

    deleted_area = geom.calculated_area

    # Create audit log entry
    audit_entry = AuditLog(
        user_id=current_user.id,
        action="DELETE_PARCEL_GEOMETRY",
        entity_type="GisGeometry",
        entity_id=geom.id,
        old_value=str(deleted_area),
        new_value=None,
        details=json.dumps({
            "parcel_id": parcel.id,
            "parcel_code": parcel.parcel_code,
            "deleted_area": deleted_area,
            "geometry": extract_raw_geometry(geom.geojson),
            "user": current_user.username or current_user.email,
        }),
    )
    latest_version = db.query(func.max(GisGeometryVersion.version_number)).filter(
        GisGeometryVersion.parcel_id == parcel.id
    ).scalar()
    db.add(GisGeometryVersion(
        parcel_id=parcel.id,
        geometry_id=geom.id,
        version_number=(latest_version or 0) + 1,
        event_type="deleted",
        geojson=geom.geojson,
        geometry_type=geom.geometry_type,
        calculated_area=geom.calculated_area,
        area_unit=geom.area_unit,
        source=geom.source,
        source_document_id=geom.source_document_id,
        source_page_number=geom.source_page_number,
        confidence=geom.confidence,
        verification_status=geom.verification_status,
        changed_by=current_user.id,
        reason="Geometry deleted by authorized user",
        is_deleted=True,
    ))
    db.add(audit_entry)

    db.delete(geom)
    db.commit()

    logger.info(f"Deleted geometry {geometry_id} for parcel {parcel.parcel_code} by user {current_user.id}")

    return {
        "status": "success",
        "message": f"Geometry removed for parcel {parcel.parcel_code}",
        "parcel_id": parcel.id,
        "deleted_geometry_id": geometry_id,
    }


@router.get("/parcels/{parcel_id}/geometry/history")
async def get_parcel_geometry_history(
    parcel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Read immutable geometry snapshots for a parcel within the caller's scope."""
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")
    authorize_parcel_access(parcel, current_user, "read", db)
    versions = db.query(GisGeometryVersion).filter(
        GisGeometryVersion.parcel_id == parcel.id
    ).order_by(GisGeometryVersion.version_number.desc()).limit(100).all()
    return {
        "parcel_id": parcel.id,
        "versions": [{
            "id": v.id,
            "geometry_id": v.geometry_id,
            "version_number": v.version_number,
            "event_type": v.event_type,
            "geometry": extract_raw_geometry(v.geojson),
            "geometry_type": v.geometry_type,
            "calculated_area": v.calculated_area,
            "area_unit": v.area_unit,
            "source": v.source,
            "source_document_id": v.source_document_id,
            "source_page_number": v.source_page_number,
            "confidence": v.confidence,
            "verification_status": v.verification_status,
            "changed_by": v.changed_by,
            "reason": v.reason,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "is_deleted": v.is_deleted,
        } for v in versions],
    }


@router.post("/spatial/query")
async def query_spatial_parcels(
    data: SpatialQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Query visible parcel geometries using PostGIS spatial operators."""
    if db.bind.dialect.name != "postgresql" or not POSTGIS_TYPES_AVAILABLE or Geography is None:
        raise HTTPException(status_code=501, detail="PostGIS spatial queries are not available on this database")

    try:
        raw_geometry = extract_raw_geometry(data.geometry)
        from shapely.geometry import shape
        query_shape = shape(raw_geometry)
        if query_shape.is_empty or not query_shape.is_valid:
            raise ValueError("Query geometry must be non-empty and valid")
        min_x, min_y, max_x, max_y = query_shape.bounds
        if min_x < -180 or max_x > 180 or min_y < -90 or max_y > 90:
            raise ValueError("Query coordinates must use longitude/latitude in EPSG:4326")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid query geometry: {exc}")

    visible_parcels = filter_parcels_by_scope(db.query(Parcel), current_user, db).with_entities(Parcel.id).statement
    query_geometry = func.ST_SetSRID(
        func.ST_GeomFromGeoJSON(json.dumps(raw_geometry, separators=(",", ":"))), 4326
    )
    parcel_geometry = GisGeometry.geometry

    if data.operation == "intersects":
        predicate = func.ST_Intersects(parcel_geometry, query_geometry)
    elif data.operation == "overlaps":
        predicate = func.ST_Overlaps(parcel_geometry, query_geometry)
    elif data.operation == "contains":
        predicate = func.ST_Contains(parcel_geometry, query_geometry)
    elif data.operation == "within":
        predicate = func.ST_Within(parcel_geometry, query_geometry)
    elif data.operation == "touches":
        predicate = func.ST_Touches(parcel_geometry, query_geometry)
    else:
        predicate = func.ST_DWithin(
            cast(parcel_geometry, Geography(srid=4326)),
            cast(query_geometry, Geography(srid=4326)),
            data.distance_meters,
        )

    matches_query = (
        db.query(GisGeometry, Parcel)
        .join(Parcel, Parcel.id == GisGeometry.parcel_id)
        .filter(Parcel.id.in_(visible_parcels), predicate)
    )
    total_matches = matches_query.count()
    matches = matches_query.order_by(Parcel.parcel_code, GisGeometry.updated_at.desc()).offset(data.offset).limit(data.limit).all()
    return {
        "operation": data.operation,
        "total": total_matches,
        "limit": data.limit,
        "offset": data.offset,
        "matches": [
            {
                "geometry_id": geometry.id,
                "parcel_id": parcel.id,
                "parcel_code": parcel.parcel_code,
                "owner": parcel.current_owner,
                "geometry": extract_raw_geometry(geometry.geojson),
                "calculated_area": geometry.calculated_area,
                "area_unit": geometry.area_unit,
            }
            for geometry, parcel in matches
        ],
    }


@router.post("/calculate-area")
async def calculate_area_endpoint(
    data: AreaCalculationRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Calculate geodesic area from any GeoJSON geometry using dynamic UTM projection.
    Returns area in acres, square meters, geometry validation, and projected CRS zone.
    """
    try:
        input_geom = data.geojson or data.geometry
        if not input_geom:
            raise HTTPException(status_code=400, detail="Missing geometry data in request payload.")
        raw_geom = extract_raw_geometry(input_geom)
        validation = validate_geometry(raw_geom)

        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid geometry: {'; '.join(validation['issues'])}"
            )

        area_acres, unit, area_sqm = calculate_area_from_geojson(raw_geom, use_projected=data.use_projected)

        return {
            "area_acres": area_acres,
            "calculated_area_acres": area_acres,
            "area_sq_meters": area_sqm,
            "calculated_area_sqm": area_sqm,
            "unit": unit,
            "geometry_type": validation["geometry_type"],
            "validation": validation,
            "utm_zone": validation.get("utm_zone") or "UTM (Dynamic Geodesic)",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Area calculation failed: {e}")
        raise HTTPException(status_code=500, detail="Area calculation failed")


@router.post("/compare-area")
async def compare_document_and_gis_area_endpoint(
    doc_area: float = Query(..., description="Document stated area in acres"),
    gis_area: float = Query(..., description="GIS calculated area in acres"),
    tolerance: float = Query(0.10, description="Tolerance fraction (default 0.10 = 10%)"),
    current_user: User = Depends(get_current_user),
):
    """
    Compare document stated area with GIS calculated area.
    Flags discrepancies based on percentage variance.
    """
    try:
        result = compare_areas(doc_area, gis_area, tolerance)
        return result
    except Exception as e:
        logger.error(f"Area comparison failed: {e}")
        raise HTTPException(status_code=500, detail="Area comparison failed")


@router.get("/stats")
async def get_gis_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get aggregate statistics of GIS coverage and discrepancies."""
    scoped_parcels = filter_parcels_by_scope(db.query(Parcel), current_user, db)
    scoped_parcel_ids = scoped_parcels.with_entities(Parcel.id).statement
    total_parcels = scoped_parcels.count()
    scoped_geometries = db.query(GisGeometry).filter(GisGeometry.parcel_id.in_(scoped_parcel_ids))
    parcels_with_geom = scoped_geometries.with_entities(GisGeometry.parcel_id).distinct().count()

    total_gis_records = scoped_geometries.count()
    total_mapped_acres = db.query(func.coalesce(func.sum(GisGeometry.calculated_area), 0.0)).filter(
        GisGeometry.parcel_id.in_(scoped_parcel_ids)
    ).scalar()

    open_gis_discrepancies = db.query(Discrepancy).filter(
        Discrepancy.parcel_id.in_(scoped_parcel_ids),
        Discrepancy.discrepancy_type.in_([DiscrepancyType.GIS_AREA_CONFLICT, DiscrepancyType.BOUNDARY_CONFLICT]),
        Discrepancy.resolution_status == "open"
    ).count()

    return {
        "total_parcels": total_parcels,
        "parcels_with_geometry": parcels_with_geom,
        "geometry_coverage_percent": round((parcels_with_geom / total_parcels * 100) if total_parcels > 0 else 0.0, 1),
        "total_gis_geometries": total_gis_records,
        "total_mapped_acres": round(total_mapped_acres, 2),
        "open_gis_discrepancies": open_gis_discrepancies,
    }
