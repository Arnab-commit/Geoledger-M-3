"""Parcel identity resolution and Digital Twin service."""

import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.models.parcel import Parcel, ParcelIdentifier, ParcelDocument
from backend.models.document import Document
from backend.models.extraction import ExtractedField
from backend.models.ownership import Owner, OwnershipEvent
from backend.models.mutation import Mutation
from backend.models.registration import Registration
from backend.models.discrepancy import Discrepancy
from backend.models.evidence import Evidence
from backend.models.gis import GisGeometry
from backend.models.verification import VerificationCase
from backend.services.normalization_service import normalize_name, normalize_identifier, normalize_area

logger = logging.getLogger("geoldger.parcel")


class ParcelResolutionNeedsReview(ValueError):
    """Raised when extracted identifiers cannot safely identify one parcel."""


def resolve_or_create_parcel(
    db: Session,
    survey_no: Optional[str] = None,
    khasra_no: Optional[str] = None,
    plot_no: Optional[str] = None,
    khata_no: Optional[str] = None,
    village: Optional[str] = None,
    district: Optional[str] = None,
    state: Optional[str] = None,
    document_id: Optional[str] = None,
    current_area: Optional[float] = None,
    area_unit: Optional[str] = "acres",
    land_classification: Optional[str] = None,
    current_owner: Optional[str] = None,
    identifier_confidence: Optional[float] = None,
) -> Parcel:
    """
    Resolve one parcel from a sufficiently reliable identifier, or create one
    only when a trusted village is available. Ambiguous cases require review.
    """
    primary_id = survey_no or khasra_no or plot_no or khata_no
    identifier_type = (
        "survey_no" if survey_no else
        "khasra_no" if khasra_no else
        "plot_no" if plot_no else
        "khata_no" if khata_no else None
    )
    identifier_type_aliases = {
        "survey_no": {"survey_no", "survey_number"},
        "khasra_no": {"khasra_no", "khasra"},
        "plot_no": {"plot_no", "plot_number"},
        "khata_no": {"khata_no", "khatian_no", "khata_number", "khatian_number"},
    }
    if primary_id:
        norm_id, _ = normalize_identifier(primary_id)
    else:
        norm_id = None

    norm_village = village.strip().title() if village else None
    norm_district = district.strip().title() if district else None

    if not norm_id or not identifier_type or identifier_confidence is None or identifier_confidence < 0.70:
        raise ParcelResolutionNeedsReview("A parcel identifier with at least 70% extraction confidence is required.")

    # A matching identifier alone can collide across villages, identifier types, or jurisdictions.
    existing_parcel = None
    candidates = (
        db.query(Parcel, ParcelIdentifier)
        .join(ParcelIdentifier, Parcel.id == ParcelIdentifier.parcel_id)
        .filter(ParcelIdentifier.identifier_value == norm_id)
        .all()
    )
    typed_candidates = [
        (parcel, identifier) for parcel, identifier in candidates
        if identifier.identifier_type in identifier_type_aliases[identifier_type]
    ]
    if candidates and not typed_candidates:
        raise ParcelResolutionNeedsReview("The identifier matches existing records under a different identifier type.")
    if typed_candidates:
        def location_matches(candidate: Parcel) -> bool:
            return (
                (not norm_village or (candidate.village or "").strip().casefold() == norm_village.casefold())
                and (not norm_district or (candidate.district or "").strip().casefold() == norm_district.casefold())
                and (not state or not candidate.state or candidate.state.strip().casefold() == state.strip().casefold())
            )

        location_candidates = {candidate.id: candidate for candidate, _ in typed_candidates if location_matches(candidate)}
        if len(location_candidates) != 1:
            raise ParcelResolutionNeedsReview(
                "The extracted parcel identifier is ambiguous or its village/district conflicts with existing records."
            )
        existing_parcel = next(iter(location_candidates.values()))
    elif not norm_village:
        raise ParcelResolutionNeedsReview("Village information is required before creating a new parcel from a document.")

    if not existing_parcel:
        # Generate new canonical Parcel ID
        parcel_code = f"PL-{uuid.uuid4().hex[:7].upper()}"

        existing_parcel = Parcel(
            parcel_code=parcel_code,
            ulpin=None,
            village=norm_village or "Unspecified Location",
            mouza=norm_village or "Unspecified Location",
            district=norm_district or "Unspecified District",
            state=state,
            current_area=current_area,
            area_unit=area_unit or "acres",
            land_classification=land_classification,
            current_owner=current_owner,
            verification_status="pending",
            consistency_score=1.0,
        )
        db.add(existing_parcel)
        db.commit()
        db.refresh(existing_parcel)

        # Add primary identifier if available
        if norm_id:
            id_record = ParcelIdentifier(
                parcel_id=existing_parcel.id,
                identifier_type=identifier_type,
                identifier_value=norm_id,
                source_document_id=document_id,
                confidence=identifier_confidence,
            )
            db.add(id_record)
            db.commit()
            logger.info(f"Created new Parcel {existing_parcel.parcel_code} ({norm_id}, {norm_village})")
        else:
            logger.info(f"Created unindexed Parcel {existing_parcel.parcel_code}")

    # Update parcel attributes if newly extracted values are present
    if current_owner:
        existing_parcel.current_owner = current_owner
    if current_area:
        existing_parcel.current_area = current_area
    if land_classification:
        existing_parcel.land_classification = land_classification
    if norm_village:
        existing_parcel.village = norm_village
        existing_parcel.mouza = norm_village
    if norm_district:
        existing_parcel.district = norm_district
    if state:
        existing_parcel.state = state
    db.commit()

    # Link document if provided
    if document_id:
        existing_link = (
            db.query(ParcelDocument)
            .filter(
                ParcelDocument.parcel_id == existing_parcel.id,
                ParcelDocument.document_id == document_id,
            )
            .first()
        )
        if not existing_link:
            link = ParcelDocument(
                parcel_id=existing_parcel.id,
                document_id=document_id,
                relationship_type="primary",
            )
            db.add(link)
            db.commit()
            logger.info(f"Linked doc {document_id[:8]} to parcel {existing_parcel.parcel_code}")

    return existing_parcel


def get_parcel_digital_twin(db: Session, parcel_id: str) -> Dict[str, Any]:
    """
    Assemble complete Parcel Digital Twin with all connected entities:
    - Identity & current attributes
    - Linked documents
    - Ownership history
    - Mutations
    - Registrations
    - GIS Geometries
    - Discrepancies & Evidence
    - Verification history
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise ValueError(f"Parcel not found: {parcel_id}")

    # Gather linked documents
    parcel_docs = db.query(ParcelDocument).filter(ParcelDocument.parcel_id == parcel.id).all()
    doc_ids = [pd.document_id for pd in parcel_docs]
    documents = db.query(Document).filter(Document.id.in_(doc_ids)).all() if doc_ids else []

    # Gather identifiers
    identifiers = db.query(ParcelIdentifier).filter(ParcelIdentifier.parcel_id == parcel.id).all()

    # Gather owners
    owners = db.query(Owner).filter(Owner.parcel_id == parcel.id).all()

    # Gather mutations
    mutations = db.query(Mutation).filter(Mutation.parcel_id == parcel.id).all()

    # Gather registrations
    registrations = db.query(Registration).filter(Registration.parcel_id == parcel.id).all()

    # Gather discrepancies
    discrepancies = db.query(Discrepancy).filter(Discrepancy.parcel_id == parcel.id).all()

    # Gather GIS geometries
    gis_list = db.query(GisGeometry).filter(GisGeometry.parcel_id == parcel.id).all()

    # Gather verification cases
    v_cases = db.query(VerificationCase).filter(VerificationCase.parcel_id == parcel.id).all()

    return {
        "identity": {
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
            "current_owner": parcel.current_owner,
            "consistency_score": parcel.consistency_score if parcel.consistency_score is not None else 1.0,
            "verification_status": parcel.verification_status,
        },
        "identifiers": [
            {
                "type": i.identifier_type,
                "value": i.identifier_value,
                "confidence": i.confidence,
            }
            for i in identifiers
        ],
        "documents": [
            {
                "id": d.id,
                "filename": d.original_filename,
                "document_type": d.document_type.value if hasattr(d.document_type, "value") else str(d.document_type),
                "upload_timestamp": d.upload_timestamp.isoformat() if d.upload_timestamp else None,
                "processing_status": d.processing_status.value if hasattr(d.processing_status, "value") else str(d.processing_status),
                "file_hash": d.file_hash,
            }
            for d in documents
        ],
        "ownership": [
            {
                "id": o.id,
                "name": o.name,
                "normalized_name": o.normalized_name,
                "father_husband_name": o.father_husband_name,
                "is_current": o.is_current,
                "share": o.ownership_share,
                "confidence": o.confidence,
            }
            for o in owners
        ],
        "mutations": [
            {
                "id": m.id,
                "mutation_number": m.mutation_number,
                "date": m.mutation_date,
                "previous_owner": m.previous_owner,
                "new_owner": m.new_owner,
                "area": m.area,
            }
            for m in mutations
        ],
        "registrations": [
            {
                "id": r.id,
                "registration_number": r.registration_number,
                "date": r.registration_date,
                "type": r.registration_type,
            }
            for r in registrations
        ],
        "discrepancies": [
            {
                "id": disc.id,
                "type": disc.discrepancy_type.value if hasattr(disc.discrepancy_type, "value") else str(disc.discrepancy_type),
                "severity": disc.severity.value if hasattr(disc.severity, "value") else str(disc.severity),
                "field_name": disc.field_name,
                "value_a": disc.value_a,
                "value_b": disc.value_b,
                "similarity_score": disc.similarity_score,
                "reason": disc.reason,
                "status": disc.resolution_status,
            }
            for disc in discrepancies
        ],
        "gis": [
            {
                "id": g.id,
                "geometry_type": g.geometry_type,
                "calculated_area": g.calculated_area,
                "area_unit": g.area_unit,
                "source": g.source,
                "is_authoritative": g.is_authoritative,
            }
            for g in gis_list
        ],
        "verification_cases": [
            {
                "id": v.id,
                "case_type": v.case_type,
                "priority": v.priority,
                "status": v.status.value if hasattr(v.status, "value") else str(v.status),
                "summary": v.summary,
            }
            for v in v_cases
        ],
    }
