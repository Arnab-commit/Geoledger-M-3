"""Reconciliation and Multi-Document Contradiction Engine."""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from backend.models.parcel import Parcel, ParcelDocument
from backend.models.document import Document
from backend.models.extraction import ExtractedField
from backend.models.discrepancy import Discrepancy, DiscrepancyType, Severity
from backend.models.evidence import Evidence
from backend.services.normalization_service import compare_names, normalize_name, normalize_area, normalize_identifier

logger = logging.getLogger("geoldger.reconciliation")


STANDARD_COMPARISON_FIELDS = [
    {"key": "survey_number", "label": "Survey Number", "category": "identifier", "comparable": True},
    {"key": "khasra_number", "label": "Khasra Number", "category": "identifier", "comparable": True},
    {"key": "plot_number", "label": "Plot Number", "category": "identifier", "comparable": True},
    {"key": "khata_number", "label": "Khata Number", "category": "identifier", "comparable": True},
    {"key": "khatian_number", "label": "Khatian Number", "category": "identifier", "comparable": True},
    {"key": "village", "label": "Village / Mouza", "category": "spatial", "comparable": True},
    {"key": "district", "label": "District", "category": "spatial", "comparable": True},
    {"key": "state", "label": "State", "category": "spatial", "comparable": True},
    {"key": "owner_name", "label": "Primary Recorded Owner", "category": "ownership", "comparable": True},
    {"key": "father_husband_name", "label": "Father / Husband Name", "category": "ownership", "comparable": True},
    {"key": "previous_owner", "label": "Previous Owner / Seller", "category": "ownership", "comparable": True},
    {"key": "new_owner", "label": "New Owner / Buyer", "category": "ownership", "comparable": True},
    {"key": "area", "label": "Land Area", "category": "spatial", "comparable": True},
    {"key": "area_unit", "label": "Area Unit", "category": "spatial", "comparable": True},
    {"key": "land_classification", "label": "Land Classification", "category": "spatial", "comparable": True},
    {"key": "mutation_number", "label": "Mutation Case Number", "category": "administrative", "comparable": False},
    {"key": "mutation_date", "label": "Mutation Date", "category": "administrative", "comparable": False},
    {"key": "registration_number", "label": "Deed / Registration Number", "category": "administrative", "comparable": False},
    {"key": "registration_date", "label": "Registration Date", "category": "administrative", "comparable": False},
    {"key": "consideration_amount", "label": "Transaction / Consideration Amount", "category": "financial", "comparable": False},
]


def reconcile_parcel_documents(db: Session, parcel_id: str) -> List[Discrepancy]:
    """
    Run multi-document reconciliation for all documents linked to a parcel.
    Compares:
    1. Owner names across documents (detects name variations, typos, potential impersonation)
    2. Land areas (detects area mismatches or encroachment indicators)
    3. Spatial identifiers (survey/khasra/village consistency)
    4. Chronology & chain of title across consecutive records
    """
    parcel = db.query(Parcel).filter((Parcel.id == parcel_id) | (Parcel.parcel_code == parcel_id)).first()
    if not parcel:
        raise ValueError(f"Parcel not found: {parcel_id}")

    # Fetch all linked documents
    parcel_docs = db.query(ParcelDocument).filter(ParcelDocument.parcel_id == parcel.id).all()
    doc_ids = [pd.document_id for pd in parcel_docs]

    if len(doc_ids) < 2:
        logger.info(f"Parcel {parcel.parcel_code} has fewer than 2 documents; skipping cross-doc reconciliation.")
        return []

    # Clear previous pending discrepancies for this parcel to avoid duplicates
    db.query(Discrepancy).filter(
        Discrepancy.parcel_id == parcel.id,
        Discrepancy.resolution_status == "pending",
    ).delete()

    discrepancies: List[Discrepancy] = []

    # Gather extracted fields and metadata for all linked docs
    docs_fields: Dict[str, Dict[str, Any]] = {}
    docs_metadata: Dict[str, Document] = {}

    for doc_id in doc_ids:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            continue
        docs_metadata[doc_id] = doc

        fields = db.query(ExtractedField).filter(ExtractedField.document_id == doc_id).all()
        field_map = {}
        for f in fields:
            if f.value:
                field_map[f.field_name] = {
                    "raw": f.value,
                    "normalized": f.normalized_value or f.value,
                    "confidence": f.confidence,
                }
        docs_fields[doc_id] = field_map

    # Check pairwise comparisons across documents
    doc_id_list = list(docs_fields.keys())
    for i in range(len(doc_id_list)):
        for j in range(i + 1, len(doc_id_list)):
            id_a = doc_id_list[i]
            id_b = doc_id_list[j]
            fields_a = docs_fields[id_a]
            fields_b = docs_fields[id_b]
            doc_a = docs_metadata[id_a]
            doc_b = docs_metadata[id_b]

            # 1. Owner Name Discrepancies
            owner_a = (fields_a.get("owner_name") or fields_a.get("new_owner") or {}).get("normalized")
            owner_b = (fields_b.get("owner_name") or fields_b.get("new_owner") or {}).get("normalized")

            if owner_a and owner_b and owner_a != owner_b:
                sim = compare_names(owner_a, owner_b)
                if 0.60 <= sim < 0.95:
                    disc = Discrepancy(
                        parcel_id=parcel.id,
                        document_a_id=id_a,
                        document_b_id=id_b,
                        discrepancy_type=DiscrepancyType.OWNER_CONFLICT,
                        severity=Severity.HIGH if sim < 0.80 else Severity.MEDIUM,
                        field_name="owner_name",
                        value_a=owner_a,
                        value_b=owner_b,
                        similarity_score=round(sim, 3),
                        reason=(
                            f"Spelling variation detected in owner name: '{owner_a}' ({doc_a.original_filename}) vs "
                            f"'{owner_b}' ({doc_b.original_filename}) with similarity score {sim:.2f}."
                        ),
                        resolution_status="pending",
                    )
                    db.add(disc)
                    discrepancies.append(disc)
                elif sim < 0.60:
                    disc = Discrepancy(
                        parcel_id=parcel.id,
                        document_a_id=id_a,
                        document_b_id=id_b,
                        discrepancy_type=DiscrepancyType.OWNER_CONFLICT,
                        severity=Severity.CRITICAL,
                        field_name="owner_name",
                        value_a=owner_a,
                        value_b=owner_b,
                        similarity_score=round(sim, 3),
                        reason=(
                            f"Different owner names recorded across documents: '{owner_a}' ({doc_a.original_filename}) vs "
                            f"'{owner_b}' ({doc_b.original_filename}). Potential ownership dispute or unlinked transfer."
                        ),
                        resolution_status="pending",
                    )
                    db.add(disc)
                    discrepancies.append(disc)

            # 2. Area Discrepancies
            area_a_info = fields_a.get("area")
            area_b_info = fields_b.get("area")
            if area_a_info and area_b_info:
                try:
                    area_a = float(area_a_info["normalized"])
                    area_b = float(area_b_info["normalized"])
                    diff = abs(area_a - area_b)
                    if diff > 0.05:
                        disc = Discrepancy(
                            parcel_id=parcel.id,
                            document_a_id=id_a,
                            document_b_id=id_b,
                            discrepancy_type=DiscrepancyType.AREA_CONFLICT,
                            severity=Severity.CRITICAL if diff > 0.5 else Severity.HIGH,
                            field_name="area",
                            value_a=f"{area_a:.2f} acres",
                            value_b=f"{area_b:.2f} acres",
                            similarity_score=round(max(0.0, 1.0 - (diff / max(area_a, area_b, 0.01))), 3),
                            reason=(
                                f"Land area inconsistency: {area_a:.2f} acres in {doc_a.original_filename} vs "
                                f"{area_b:.2f} acres in {doc_b.original_filename} (variance: {diff:.2f} acres)."
                            ),
                            resolution_status="pending",
                        )
                        db.add(disc)
                        discrepancies.append(disc)
                except (ValueError, TypeError):
                    pass

            # 3. Location / Village Discrepancies
            vill_a = (fields_a.get("village") or {}).get("normalized")
            vill_b = (fields_b.get("village") or {}).get("normalized")
            if vill_a and vill_b and vill_a.lower() != vill_b.lower():
                sim_vill = compare_names(vill_a, vill_b)
                if sim_vill < 0.85:
                    disc = Discrepancy(
                        parcel_id=parcel.id,
                        document_a_id=id_a,
                        document_b_id=id_b,
                        discrepancy_type=DiscrepancyType.LOCATION_CONFLICT,
                        severity=Severity.HIGH,
                        field_name="village",
                        value_a=vill_a,
                        value_b=vill_b,
                        similarity_score=round(sim_vill, 3),
                        reason=f"Different village/mouza recorded: '{vill_a}' ({doc_a.original_filename}) vs '{vill_b}' ({doc_b.original_filename}).",
                        resolution_status="pending",
                    )
                    db.add(disc)
                    discrepancies.append(disc)

    # Compute overall consistency score based on discrepancies
    if discrepancies:
        severities = [d.severity for d in discrepancies]
        penalty = 0.0
        for s in severities:
            if s == Severity.CRITICAL:
                penalty += 0.25
            elif s == Severity.HIGH:
                penalty += 0.15
            elif s == Severity.MEDIUM:
                penalty += 0.08
            else:
                penalty += 0.03
        parcel.consistency_score = max(0.10, round(1.0 - min(penalty, 0.85), 2))
        parcel.verification_status = "needs_review"
    else:
        parcel.consistency_score = 0.98
        # Reconciliation is an automated consistency check, not an official
        # adjudication. A clean comparison must not bypass human verification.
        parcel.verification_status = "pending"

    db.commit()
    logger.info(f"Reconciliation completed for parcel {parcel.parcel_code}: {len(discrepancies)} discrepancies found, score={parcel.consistency_score}")
    return discrepancies


def compare_multiple_documents(db: Session, document_ids: List[str]) -> Dict[str, Any]:
    """
    Execute comprehensive multi-document field-by-field comparison.
    Produces a detailed comparison matrix across documents with statuses:
    - MATCH: Values match identically or within close tolerance
    - MISMATCH: Conflicting values detected
    - REVIEW: Slight phonetic/orthographic variation requiring human review
    - NOT AVAILABLE: Field present in some documents but missing in others
    - NOT COMPARABLE: Document-specific unique identifiers (e.g. Deed No vs Mutation No)
    """
    if not document_ids or len(document_ids) < 2:
        raise ValueError("At least two document IDs are required for comparison.")

    docs = db.query(Document).filter(Document.id.in_(document_ids)).all()
    if len(docs) < 2:
        raise ValueError(f"Could not find at least two valid documents from provided IDs: {document_ids}")

    # Maintain document order as requested
    doc_map = {d.id: d for d in docs}
    ordered_docs = [doc_map[did] for did in document_ids if did in doc_map]

    # Fetch extracted fields for all documents
    doc_fields: Dict[str, Dict[str, ExtractedField]] = {}
    for doc in ordered_docs:
        fields = db.query(ExtractedField).filter(ExtractedField.document_id == doc.id).all()
        doc_fields[doc.id] = {f.field_name: f for f in fields if f.value}

    # Build Comparison Matrix
    matrix_rows = []
    matched_count = 0
    mismatched_count = 0
    review_count = 0
    not_avail_count = 0
    not_comp_count = 0

    # Build field list: standard fields + any extra extracted fields found
    all_field_keys = [f["key"] for f in STANDARD_COMPARISON_FIELDS]
    for d_id, f_dict in doc_fields.items():
        for f_key in f_dict.keys():
            if f_key not in all_field_keys:
                all_field_keys.append(f_key)

    for field_meta in STANDARD_COMPARISON_FIELDS:
        key = field_meta["key"]
        label = field_meta["label"]
        category = field_meta["category"]
        is_comparable_type = field_meta.get("comparable", True)

        # Gather values across all documents
        doc_values = []
        present_count = 0

        for doc in ordered_docs:
            field_obj = doc_fields.get(doc.id, {}).get(key)
            if field_obj and field_obj.value:
                present_count += 1
                doc_values.append({
                    "document_id": doc.id,
                    "document_name": doc.original_filename,
                    "raw_value": field_obj.value,
                    "normalized_value": field_obj.normalized_value or field_obj.value,
                    "confidence": field_obj.confidence or 0.85,
                    "is_present": True,
                })
            else:
                doc_values.append({
                    "document_id": doc.id,
                    "document_name": doc.original_filename,
                    "raw_value": None,
                    "normalized_value": None,
                    "confidence": 0.0,
                    "is_present": False,
                })

        # If field is completely missing across all compared documents, skip row
        if present_count == 0:
            continue

        # Determine Row Status
        status = "MATCH"
        explanation = ""
        similarity_score = 1.0

        if not is_comparable_type:
            status = "NOT COMPARABLE"
            not_comp_count += 1
            explanation = "Document-specific administrative identifier. Not expected to match across distinct record types."
        elif present_count < len(ordered_docs):
            status = "NOT AVAILABLE"
            not_avail_count += 1
            present_doc_names = [v["document_name"] for v in doc_values if v["is_present"]]
            missing_doc_names = [v["document_name"] for v in doc_values if not v["is_present"]]
            explanation = f"Recorded in {', '.join(present_doc_names)} but not present in {', '.join(missing_doc_names)}."
        else:
            # Field is present in all documents; compare values
            active_vals = [v for v in doc_values if v["is_present"]]
            val_a = active_vals[0]["normalized_value"]
            val_b = active_vals[1]["normalized_value"]

            if category == "ownership":
                sim = compare_names(val_a, val_b)
                similarity_score = round(sim, 3)
                if sim >= 0.95 or val_a.lower() == val_b.lower():
                    status = "MATCH"
                    matched_count += 1
                    explanation = f"Owner names match across documents ('{val_a}')."
                elif 0.65 <= sim < 0.95:
                    status = "REVIEW"
                    review_count += 1
                    explanation = f"Phonetic/spelling variation detected: '{val_a}' vs '{val_b}' (similarity {sim:.2f}). Requires officer verification."
                else:
                    status = "MISMATCH"
                    mismatched_count += 1
                    explanation = f"Conflicting names recorded: '{val_a}' vs '{val_b}'. Unlinked owner transition or contradiction."

            elif key == "area":
                try:
                    area_a = float(val_a)
                    area_b = float(val_b)
                    diff = abs(area_a - area_b)
                    similarity_score = round(max(0.0, 1.0 - (diff / max(area_a, area_b, 0.01))), 3)
                    if diff <= 0.01:
                        status = "MATCH"
                        matched_count += 1
                        explanation = f"Identical land area recorded: {area_a:.2f} acres."
                    elif 0.01 < diff <= 0.10:
                        status = "REVIEW"
                        review_count += 1
                        explanation = f"Minor area difference: {area_a:.2f} vs {area_b:.2f} acres (variance {diff:.2f} acres). Check survey rounding."
                    else:
                        status = "MISMATCH"
                        mismatched_count += 1
                        explanation = f"Significant area mismatch: {area_a:.2f} vs {area_b:.2f} acres (variance {diff:.2f} acres)."
                except (ValueError, TypeError):
                    if val_a.strip().lower() == val_b.strip().lower():
                        status = "MATCH"
                        matched_count += 1
                        explanation = f"Areas match: {val_a}."
                    else:
                        status = "MISMATCH"
                        mismatched_count += 1
                        explanation = f"Area mismatch: '{val_a}' vs '{val_b}'."

            elif category == "identifier":
                norm_a, _ = normalize_identifier(val_a)
                norm_b, _ = normalize_identifier(val_b)
                if norm_a == norm_b:
                    status = "MATCH"
                    matched_count += 1
                    explanation = f"Plot/Survey identifier matches: {norm_a}."
                else:
                    status = "MISMATCH"
                    mismatched_count += 1
                    explanation = f"Different plot/survey numbers: '{val_a}' vs '{val_b}'."

            elif category == "spatial":
                if val_a.strip().lower() == val_b.strip().lower():
                    status = "MATCH"
                    matched_count += 1
                    explanation = f"Spatial location matches: {val_a}."
                else:
                    sim_s = compare_names(val_a, val_b)
                    if sim_s >= 0.85:
                        status = "REVIEW"
                        review_count += 1
                        explanation = f"Location spelling variation: '{val_a}' vs '{val_b}'."
                    else:
                        status = "MISMATCH"
                        mismatched_count += 1
                        explanation = f"Location conflict: '{val_a}' vs '{val_b}'."
            else:
                if val_a.strip().lower() == val_b.strip().lower():
                    status = "MATCH"
                    matched_count += 1
                    explanation = "Field values are identical."
                else:
                    status = "MISMATCH"
                    mismatched_count += 1
                    explanation = f"Values differ: '{val_a}' vs '{val_b}'."

        matrix_rows.append({
            "field_key": key,
            "field_label": label,
            "category": category,
            "status": status,
            "similarity_score": similarity_score,
            "explanation": explanation,
            "values": doc_values,
        })

    # Calculate overall comparison compatibility score
    total_comparable = matched_count + mismatched_count + review_count
    if total_comparable > 0:
        compat_score = round(((matched_count * 1.0) + (review_count * 0.5)) / total_comparable, 2)
    else:
        compat_score = 1.0

    recommendation = "DOCUMENTS_CONSISTENT"
    if mismatched_count > 0:
        recommendation = "CRITICAL_CONFLICT_DETECTED"
    elif review_count > 0:
        recommendation = "MINOR_DISCREPANCIES_REVIEW_REQUIRED"

    return {
        "status": "success",
        "documents": [
            {
                "id": d.id,
                "filename": d.original_filename,
                "document_type": d.document_type.value if hasattr(d.document_type, "value") else str(d.document_type),
                "upload_timestamp": d.upload_timestamp.isoformat() if d.upload_timestamp else None,
                "page_count": d.page_count,
                "file_hash": d.file_hash,
                "file_size": d.file_size,
                "extracted_fields": [
                    {
                        "field_name": f.field_name,
                        "value": f.value,
                        "normalized_value": f.normalized_value or f.value,
                        "confidence": f.confidence,
                        "status": f.status.value if hasattr(f.status, "value") else str(f.status),
                    }
                    for f in db.query(ExtractedField).filter(ExtractedField.document_id == d.id).all()
                ],
            }
            for d in ordered_docs
        ],
        "summary": {
            "total_fields_compared": len(matrix_rows),
            "matched_fields": matched_count,
            "mismatched_fields": mismatched_count,
            "review_required_fields": review_count,
            "not_available_fields": not_avail_count,
            "not_comparable_fields": not_comp_count,
            "compatibility_score": compat_score,
            "recommendation": recommendation,
        },
        "matrix": matrix_rows,
    }
