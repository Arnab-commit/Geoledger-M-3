"""Land Record Timeline reconstruction and chronology validation service."""

import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from backend.models.parcel import Parcel, ParcelDocument
from backend.models.document import Document
from backend.models.extraction import ExtractedField
from backend.models.ownership import Owner, OwnershipEvent
from backend.models.mutation import Mutation
from backend.models.registration import Registration
from backend.services.normalization_service import compare_names

logger = logging.getLogger("geoldger.timeline")


def _extract_year_and_date(date_str: Optional[str], fallback_dt: Optional[datetime] = None) -> tuple[Optional[int], str]:
    """Parse date string to extract (year, sortable_date_str)."""
    if date_str:
        # Match YYYY-MM-DD
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_str)
        if m:
            year = int(m.group(1))
            return year, f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # Match DD/MM/YYYY or DD-MM-YYYY
        m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", date_str)
        if m:
            year = int(m.group(3))
            return year, f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

        # Match 4-digit year alone
        m = re.search(r"\b(19\d{2}|20\d{2})\b", date_str)
        if m:
            year = int(m.group(1))
            return year, f"{year}-01-01"

    if fallback_dt:
        return fallback_dt.year, fallback_dt.strftime("%Y-%m-%d")

    return None, "1900-01-01"


def get_parcel_timeline(db: Session, parcel_id: str) -> Dict[str, Any]:
    """
    Reconstruct chronological history of events for a parcel from actual database records.
    Parses dates and extracted fields to order events and detect chain-of-title anomalies.
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise ValueError(f"Parcel not found: {parcel_id}")

    parcel_docs = db.query(ParcelDocument).filter(ParcelDocument.parcel_id == parcel.id).all()
    doc_ids = [pd.document_id for pd in parcel_docs]

    if not doc_ids:
        return {
            "parcel_code": parcel.parcel_code,
            "ulpin": parcel.ulpin,
            "village": parcel.village,
            "total_events": 0,
            "earliest_year": None,
            "latest_year": None,
            "chain_of_title_status": "NO_RECORDS",
            "timeline_consistency_score": 1.0,
            "events": [],
        }

    events = []

    for doc_id in doc_ids:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            continue

        fields = db.query(ExtractedField).filter(ExtractedField.document_id == doc_id).all()
        f_map = {f.field_name: f.normalized_value or f.value for f in fields if f.value}

        # Determine date from extracted fields or document metadata
        raw_date = (
            f_map.get("registration_date")
            or f_map.get("mutation_date")
            or f_map.get("date")
        )
        year, sortable_date = _extract_year_and_date(raw_date, doc.upload_timestamp)

        # Build title and event type based on actual document type and extracted identifiers
        doc_type_val = doc.document_type.value if hasattr(doc.document_type, "value") else str(doc.document_type)
        reg_no = f_map.get("registration_number")
        mut_no = f_map.get("mutation_number")
        owner_name = f_map.get("owner_name") or f_map.get("new_owner")
        prev_owner = f_map.get("previous_owner")
        father_name = f_map.get("father_husband_name")
        area_val = f_map.get("area")
        area_unit = f_map.get("area_unit") or "Acres"

        area_display = f"{area_val} {area_unit}" if area_val else "Area not recorded"

        title = doc.original_filename
        if doc_type_val == "mutation" or mut_no:
            title = f"Revenue Mutation {mut_no}" if mut_no else f"Revenue Mutation ({doc.original_filename})"
            event_type = "MUTATION_ORDER"
            desc = f"Mutation recorded for property."
            if prev_owner and owner_name:
                desc = f"Mutation records transfer from {prev_owner} to {owner_name}."
            elif owner_name:
                desc = f"Mutation records {owner_name} as recorded owner."
        elif doc_type_val in ["sale_deed", "registration"] or reg_no:
            title = f"Registered Deed {reg_no}" if reg_no else f"Registered Document ({doc.original_filename})"
            event_type = "TRANSFER_SALE" if "sale" in doc.original_filename.lower() else "REGISTRATION"
            desc = f"Registered transaction recorded."
            if prev_owner and owner_name:
                desc = f"Deed transfers property from {prev_owner} to {owner_name}."
            elif owner_name:
                desc = f"Document records {owner_name} as party/owner."
        elif doc_type_val in ["ror", "khatian", "khasra"]:
            title = f"Record of Rights ({doc.original_filename})"
            event_type = "RECORD_OF_RIGHTS"
            desc = f"Record of Rights records {owner_name or 'unspecified owner'}."
        else:
            event_type = "DOCUMENT_RECORD"
            desc = f"Document linked to parcel: {doc.original_filename}"

        event = {
            "document_id": doc.id,
            "document_filename": doc.original_filename,
            "document_type": doc_type_val.upper(),
            "year": year,
            "date": sortable_date if sortable_date != "1900-01-01" else (raw_date or "Date not stated"),
            "event_type": event_type,
            "title": title,
            "recorded_owner": owner_name or "Not detected",
            "previous_owner": prev_owner,
            "father_name": father_name,
            "area": area_display,
            "status": "info",
            "flag": "Standard Record",
            "description": desc,
        }
        events.append(event)

    # Sort events chronologically by date
    events.sort(key=lambda x: str(x.get("date", "1900-01-01")))

    # Perform chronological chain-of-title validation across ordered events
    for i in range(len(events)):
        curr = events[i]
        if i == 0:
            curr["status"] = "baseline"
            curr["flag"] = "Root Record"
            continue

        prev = events[i - 1]
        prev_owner = prev.get("recorded_owner")
        curr_owner = curr.get("recorded_owner")
        curr_stated_prev = curr.get("previous_owner")

        # Case 1: Stated previous owner in current doc does not match previous recorded owner
        if curr_stated_prev and prev_owner and prev_owner != "Not detected":
            sim = compare_names(curr_stated_prev, prev_owner)
            if sim < 0.65:
                curr["status"] = "discrepancy"
                curr["flag"] = f"Unlinked Predecessor ({curr_stated_prev} vs {prev_owner})"
                curr["description"] += f" Stated seller/prior owner '{curr_stated_prev}' differs from previously recorded owner '{prev_owner}'."
            elif 0.65 <= sim < 0.95:
                curr["status"] = "warning"
                curr["flag"] = f"Spelling Variation ({curr_stated_prev} vs {prev_owner})"
                curr["description"] += f" Name variation detected between '{curr_stated_prev}' and '{prev_owner}'."

        # Case 2: Direct owner change between records without intervening transfer/seller info
        elif curr_owner and prev_owner and curr_owner != "Not detected" and prev_owner != "Not detected" and curr_owner != prev_owner:
            sim = compare_names(curr_owner, prev_owner)
            if sim < 0.65 and curr.get("event_type") == "RECORD_OF_RIGHTS":
                curr["status"] = "discrepancy"
                curr["flag"] = f"Unlinked Owner Transition ({prev_owner} → {curr_owner})"
                curr["description"] += f" Record names '{curr_owner}' without explicit transfer deed from previous owner '{prev_owner}'."
            elif 0.65 <= sim < 0.95:
                curr["status"] = "warning"
                curr["flag"] = f"Spelling Variation ({prev_owner} vs {curr_owner})"
                curr["description"] += f" Phonetic name difference between records: '{prev_owner}' and '{curr_owner}'."
            else:
                curr["status"] = "valid_transfer"
                curr["flag"] = "Ownership Updated"
        else:
            curr["status"] = "consistent"
            curr["flag"] = "Consistent Record"

    has_anomalies = any(e.get("status") in ["warning", "discrepancy", "anomaly"] for e in events)
    summary = {
        "parcel_code": parcel.parcel_code,
        "ulpin": parcel.ulpin,
        "village": parcel.village,
        "total_events": len(events),
        "earliest_year": events[0]["year"] if events else None,
        "latest_year": events[-1]["year"] if events else None,
        "chain_of_title_status": "DISCREPANCIES_DETECTED" if has_anomalies else "CLEAR",
        "timeline_consistency_score": 0.80 if has_anomalies else 0.98,
        "events": events,
    }

    return summary
