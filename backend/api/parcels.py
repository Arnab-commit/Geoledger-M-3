"""Parcel API endpoints."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.database import get_db
from backend.api.auth import get_current_user
from backend.models.user import User
from backend.models.parcel import Parcel
from backend.services.parcel_service import get_parcel_digital_twin
from backend.services.reconciliation_service import reconcile_parcel_documents
from backend.services.timeline_service import get_parcel_timeline

from backend.security.jurisdiction import filter_parcels_by_scope
from backend.security.authorization import authorize_parcel_access, log_security_event

logger = logging.getLogger("geoldger.api.parcels")

router = APIRouter(prefix="/api/parcels", tags=["parcels"])


class ParcelListResponse(BaseModel):
    """Response for parcel list."""
    id: str
    parcel_code: str
    ulpin: Optional[str]
    village: str
    district: str
    current_owner: Optional[str]
    current_area: Optional[float]
    area_unit: Optional[str]
    verification_status: str
    consistency_score: Optional[float]
    document_count: int


@router.get("", response_model=List[ParcelListResponse])
async def list_parcels(
    village: Optional[str] = Query(None, description="Filter by village"),
    district: Optional[str] = Query(None, description="Filter by district"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    search: Optional[str] = Query(None, description="Search query across code, ULPIN, or owner"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List parcels with scope filtering based on user role and authorized jurisdiction."""
    query = db.query(Parcel)

    if village:
        query = query.filter(Parcel.village.ilike(f"%{village}%"))
    if district:
        query = query.filter(Parcel.district.ilike(f"%{district}%"))
    if verification_status:
        query = query.filter(Parcel.verification_status == verification_status)
    if search:
        query = query.filter(
            (Parcel.parcel_code.ilike(f"%{search}%")) |
            (Parcel.ulpin.ilike(f"%{search}%")) |
            (Parcel.current_owner.ilike(f"%{search}%"))
        )

    # Scoping enforcement
    scoped_query = filter_parcels_by_scope(query, current_user, db)
    parcels = scoped_query.offset(offset).limit(limit).all()

    # Count linked documents for each parcel
    from backend.models.parcel import ParcelDocument
    result = []
    for p in parcels:
        doc_count = db.query(ParcelDocument).filter(ParcelDocument.parcel_id == p.id).count()
        result.append(
            ParcelListResponse(
                id=p.id,
                parcel_code=p.parcel_code,
                ulpin=p.ulpin,
                village=p.village or "—",
                district=p.district or "—",
                current_owner=p.current_owner,
                current_area=p.current_area,
                area_unit=p.area_unit,
                verification_status=p.verification_status,
                consistency_score=p.consistency_score,
                document_count=doc_count,
            )
        )

    logger.info(f"Listed {len(result)} scoped parcels for user {current_user.username}")
    return result


@router.get("/{parcel_id}")
async def get_parcel(
    parcel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get complete Parcel Digital Twin with strict jurisdiction & ownership authorization."""
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    authorize_parcel_access(parcel, current_user, "read", db)

    try:
        twin = get_parcel_digital_twin(db, parcel.id)
        logger.info(f"Retrieved Parcel Digital Twin: {parcel.id[:8]} for {current_user.username}")
        return twin
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving parcel {parcel_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve parcel")


@router.post("/{parcel_id}/reconcile")
async def reconcile_parcel(
    parcel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run multi-document reconciliation for a parcel.
    Restricted to authorized jurisdiction or parcel owners.
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    authorize_parcel_access(parcel, current_user, "reconcile", db)

    try:
        discrepancies = reconcile_parcel_documents(db, parcel.id)
        return {
            "status": "success",
            "parcel_id": parcel.id,
            "discrepancies_found": len(discrepancies),
            "discrepancies": [
                {
                    "id": d.id,
                    "type": d.discrepancy_type.value if hasattr(d.discrepancy_type, "value") else str(d.discrepancy_type),
                    "severity": d.severity.value if hasattr(d.severity, "value") else str(d.severity),
                    "field_name": d.field_name,
                    "value_a": d.value_a,
                    "value_b": d.value_b,
                    "similarity": d.similarity_score,
                    "reason": d.reason,
                    "status": d.resolution_status,
                }
                for d in discrepancies
            ],
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Reconciliation failed for parcel {parcel_id}: {e}")
        raise HTTPException(status_code=500, detail="Reconciliation failed")


@router.get("/{parcel_id}/timeline")
async def get_timeline(
    parcel_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get chronological Land Record Timeline for a parcel.
    Restricted to authorized jurisdiction or parcel owners.
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise HTTPException(status_code=404, detail="Parcel not found")

    authorize_parcel_access(parcel, current_user, "read", db)

    try:
        timeline = get_parcel_timeline(db, parcel.id)
        return timeline
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Timeline retrieval failed for parcel {parcel_id}: {e}")
        raise HTTPException(status_code=500, detail="Timeline retrieval failed")

