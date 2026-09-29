"""Document processing API endpoint."""

import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.user import User
from backend.models.document import Document, DocumentPage, ProcessingStatus, DocumentType
from backend.models.ocr import OcrResult
from backend.models.extraction import ExtractedField
from backend.models.evidence import Evidence
from backend.models.verification import VerificationCase, VerificationStatus
from backend.api.auth import get_current_user
from backend.services.document_service import get_document, update_document_status
from backend.services.preprocessing_service import preprocess_image, pdf_to_images, get_image_dimensions
from backend.services.ocr_service import process_image_ocr
from backend.services.extraction_service import extract_fields_from_text, save_extracted_fields
from backend.services.normalization_service import (
    normalize_name,
    normalize_area,
    normalize_date,
    normalize_identifier,
)
from backend.services.parcel_service import resolve_or_create_parcel, ParcelResolutionNeedsReview
from backend.models.ownership import Owner
from backend.models.mutation import Mutation
from backend.models.registration import Registration
from backend.services.audit_service import log_action

logger = logging.getLogger("geoldger.process")
router = APIRouter(prefix="/api/documents", tags=["Processing"])


@router.post("/{document_id}/process")
async def process_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute full OCR and extraction pipeline for a document.
    1. Preprocessing (PDF 300 DPI conversion, non-destructive image enhancement)
    2. Hybrid OCR with bounding boxes (Tesseract neural multilingual + digital stream)
    3. 23-field structured extraction (Form layout, tabular ownership, regex)
    4. Normalization (Dates, Names, Areas to standard Acres, Identifiers)
    5. Evidence creation & Parcel Digital Twin synchronization
    """
    try:
        doc = get_document(db, document_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found")
    # Authorize document access & processing
    from backend.security.authorization import authorize_document_access
    authorize_document_access(doc, current_user, "process", db)

    file_path = Path(doc.file_path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Source file not found on disk")

    try:
        # Step 1: Preprocessing
        update_document_status(db, document_id, ProcessingStatus.PREPROCESSING)

        processed_dir = Path("uploads/processed") / document_id
        processed_dir.mkdir(parents=True, exist_ok=True)

        image_paths = []
        is_pdf = (doc.mime_type == "application/pdf" or file_path.suffix.lower() == ".pdf")

        if is_pdf:
            image_paths = pdf_to_images(file_path, processed_dir)
            doc.page_count = len(image_paths)
        else:
            # Single image preprocessing
            enhanced_path = processed_dir / f"enhanced_{file_path.name}"
            try:
                preprocess_image(file_path, enhanced_path)
                image_paths = [enhanced_path]
            except Exception as e:
                logger.warning(f"Preprocessing image enhancement failed, using original: {e}")
                image_paths = [file_path]
            doc.page_count = 1

        # Clear any prior processing records for this document to allow clean re-processing
        db.query(DocumentPage).filter(DocumentPage.document_id == document_id).delete()
        db.query(OcrResult).filter(OcrResult.document_id == document_id).delete()
        db.query(Evidence).filter(Evidence.document_id == document_id).delete()
        db.commit()

        # Step 2: Hybrid OCR & Digital Stream Processing
        update_document_status(db, document_id, ProcessingStatus.OCR_PROCESSING)

        all_extracted_text = []
        total_ocr_confidence = 0.0

        pdf_doc = None
        if is_pdf:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            try:
                pdf_doc = fitz.open(str(file_path))
            except Exception as e:
                logger.warning(f"Could not open PDF with PyMuPDF: {e}")
                pdf_doc = None

        for page_idx, img_path in enumerate(image_paths, start=1):
            width, height = get_image_dimensions(img_path)
            doc_page = DocumentPage(
                document_id=document_id,
                page_number=page_idx,
                original_image_path=str(file_path),
                processed_image_path=str(img_path),
                width=width,
                height=height,
            )
            db.add(doc_page)

            # Run OCR on 300 DPI preprocessed image
            ocr_res = process_image_ocr(img_path, language=doc.language or "all", original_filename=doc.original_filename)

            embedded_text = ""
            if pdf_doc and (page_idx - 1) < len(pdf_doc):
                try:
                    embedded_text = pdf_doc[page_idx - 1].get_text()
                except Exception:
                    embedded_text = ""

            # If PDF has high-fidelity digital text stream, merge it with OCR
            if len(embedded_text.strip()) > 30:
                combined_page_text = f"{embedded_text}\n{ocr_res['text']}"
                all_extracted_text.append(combined_page_text)
                total_ocr_confidence += 0.98
            else:
                all_extracted_text.append(ocr_res["text"])
                total_ocr_confidence += max(ocr_res.get("confidence", 0.85), 0.5)

            # Update document detected language
            if ocr_res.get("detected_language"):
                doc.language = ocr_res["detected_language"]

            # Save OcrResult blocks
            for block in ocr_res.get("blocks", []):
                bbox = block.get("bbox", [0, 0, 0, 0])
                ocr_entry = OcrResult(
                    document_id=document_id,
                    page_number=page_idx,
                    text=block["text"],
                    confidence=block["confidence"],
                    bbox_x1=bbox[0] if len(bbox) > 0 else None,
                    bbox_y1=bbox[1] if len(bbox) > 1 else None,
                    bbox_x2=bbox[2] if len(bbox) > 2 else None,
                    bbox_y2=bbox[3] if len(bbox) > 3 else None,
                    block_type=block.get("block_type", "word"),
                )
                db.add(ocr_entry)

        if pdf_doc:
            pdf_doc.close()

        db.commit()

        # Step 3: Structured Field Extraction
        update_document_status(db, document_id, ProcessingStatus.EXTRACTION)
        combined_text = "\n".join(all_extracted_text)

        # Empty OCR must not create an unindexed/placeholder parcel or appear completed.
        if not combined_text.strip():
            pending_case = db.query(VerificationCase).filter(
                VerificationCase.document_id == document_id,
                VerificationCase.status == VerificationStatus.PENDING,
            ).first()
            if not pending_case:
                db.add(VerificationCase(
                    document_id=document_id,
                    case_type="low_confidence_ocr_review",
                    priority="high",
                    status=VerificationStatus.PENDING,
                    summary=f"No readable text was extracted from {doc.original_filename}; manual review is required.",
                    confidence=0.0,
                    submitted_by=current_user.id,
                ))
            update_document_status(db, document_id, ProcessingStatus.HUMAN_REVIEW_REQUIRED)
            db.commit()
            log_action(
                db=db,
                action="PROCESSING_REVIEW_REQUIRED",
                entity_type="document",
                entity_id=document_id,
                user_id=current_user.id,
                details="OCR returned no readable text; no parcel or extracted fields were created.",
            )
            return {
                "status": "review_required",
                "document_id": document_id,
                "page_count": doc.page_count,
                "fields_extracted": 0,
                "parcel_id": None,
                "reason": "No readable text was extracted; manual review is required.",
            }

        # Multilingual Document Type classification across Indic languages
        lower_text = combined_text.lower()
        if any(w in combined_text for w in ["মিউটেশন", "नामांतरण", "दाखिल खारिज", "फेरफार", "ફેરફાર", "பட்டா மாறுதல்", "ఇంతకాల్", "ದಾಖಲಾತಿ"]) or "mutation" in lower_text or "kharij" in lower_text:
            doc.document_type = DocumentType.MUTATION
        elif any(w in combined_text for w in ["বিক্রয় দলিল", "बैनामा", "दस्ताऐवज", "பத்திர", "దస్తావేజు", "ದಸ್ತಾವೇಜು", "खरेदी खत", "વેચાણ દસ્તાવેજ"]) or "sale deed" in lower_text or "buyer" in lower_text or "deed" in lower_text:
            doc.document_type = DocumentType.SALE_DEED
        elif any(w in combined_text for w in ["খতিয়ান", "खतियान", "सातबारा", "7/12", "அடங்கல்", "பட்டா", "పట్టాదారు పాసుపుస్తకం", "ಪಹಣಿ", "ଅଧିକାର ପତ୍ର"]) or "record of rights" in lower_text or "khatiyan" in lower_text or "khatian" in lower_text or "ror" in lower_text:
            doc.document_type = DocumentType.ROR
        elif any(w in combined_text for w in ["বাটোয়ারা", "बंटवारा", "फाळणी", "பாகப்பிரிவினை", "విభజన", "ವಿಭಾಗ"]) or "partition" in lower_text:
            doc.document_type = DocumentType.PARTITION
        elif any(w in combined_text for w in ["উত্তরাধিকার", "वारिस", "वारसा", "வாரிசு", "వారసత్వ", "ವಾರಸು"]) or "inheritance" in lower_text:
            doc.document_type = DocumentType.INHERITANCE
        elif any(w in combined_text for w in ["নিবন্ধন", "पंजीकरण", "नोंदणी", "નોંધણી", "பதிவு", "రిజిస్ట్రేషన్", "ನೋಂದಣಿ"]) or "registration" in lower_text:
            doc.document_type = DocumentType.REGISTRATION
        else:
            doc.document_type = DocumentType.HISTORICAL

        doc.classification_confidence = 0.94

        extracted_dict = extract_fields_from_text(combined_text)
        saved_fields = save_extracted_fields(db, document_id, extracted_dict)

        # Step 4: Normalization
        update_document_status(db, document_id, ProcessingStatus.VALIDATION)
        for field in saved_fields:
            if not field.value:
                continue

            if field.ai_extracted_value is None:
                field.ai_extracted_value = field.value

            if field.field_name in ["owner_name", "father_husband_name", "previous_owner", "new_owner", "co_owner"]:
                norm_val, _ = normalize_name(field.value)
                field.normalized_value = norm_val
            elif field.field_name == "area":
                unit_field = next((f for f in saved_fields if f.field_name == "area_unit"), None)
                norm_acres, _, _ = normalize_area(field.value, unit_field.value if unit_field else None)
                field.normalized_value = str(norm_acres) if norm_acres is not None else field.value
            elif field.field_name in ["mutation_date", "registration_date"]:
                norm_d, _ = normalize_date(field.value)
                field.normalized_value = norm_d
            elif field.field_name in ["survey_number", "khasra_number", "plot_number", "khata_number", "khatian_number", "patta_number"]:
                norm_id, _ = normalize_identifier(field.value)
                field.normalized_value = norm_id

            # Create Evidence for extracted fields with values
            if field.value:
                evidence = Evidence(
                    document_id=document_id,
                    field_name=field.field_name,
                    value=field.value,
                    page_number=field.page_number or 1,
                    ocr_confidence=total_ocr_confidence / max(len(image_paths), 1),
                    extraction_confidence=field.confidence,
                    description=f"Extracted from {field.extraction_method} match: {field.raw_text}",
                )
                db.add(evidence)

        # Step 5: Resolve Parcel & Link Entities
        field_dict = {f.field_name: f.normalized_value or f.value for f in saved_fields if f.value}
        fields_by_name = {field.field_name: field for field in saved_fields}
        survey_val = field_dict.get("survey_number")
        plot_val = field_dict.get("plot_number")
        khasra_val = field_dict.get("khasra_number")
        khata_val = field_dict.get("khata_number") or field_dict.get("khatian_number")
        village_val = field_dict.get("village") or field_dict.get("mouza")
        district_val = field_dict.get("district")
        tehsil_val = field_dict.get("tehsil")
        state_val = field_dict.get("state")

        village_field_name = "village" if field_dict.get("village") else "mouza"
        village_field = fields_by_name.get(village_field_name)
        district_field = fields_by_name.get("district")
        state_field = fields_by_name.get("state")
        tehsil_field = fields_by_name.get("tehsil")
        trusted_village = village_val if village_field and village_field.confidence is not None and village_field.confidence >= 0.70 else None
        trusted_district = district_val if district_field and district_field.confidence is not None and district_field.confidence >= 0.70 else None
        trusted_state = state_val if state_field and state_field.confidence is not None and state_field.confidence >= 0.70 else None
        trusted_tehsil = tehsil_val if tehsil_field and tehsil_field.confidence is not None and tehsil_field.confidence >= 0.70 else None
        # Do not promote low-confidence OCR values into document jurisdiction metadata.
        if trusted_district and not doc.district:
            doc.district = trusted_district
        if trusted_state and not doc.state:
            doc.state = trusted_state
        if trusted_village and not doc.village:
            doc.village = trusted_village
        owner_name = field_dict.get("owner_name") or field_dict.get("new_owner")
        area_str = field_dict.get("area")
        area_unit_str = field_dict.get("area_unit") or "acres"
        land_class = field_dict.get("land_classification")

        current_area_val = None
        if area_str:
            try:
                current_area_val = float(area_str)
            except ValueError:
                current_area_val = None

        # Only use a sufficiently reliable extracted identifier to create or
        # attach a parcel. Preserve uncertain documents for human association.
        identifier_candidates = []
        for field_name, value in (
            ("survey_number", survey_val),
            ("khasra_number", khasra_val),
            ("plot_number", plot_val),
            ("khata_number", field_dict.get("khata_number")),
            ("khatian_number", field_dict.get("khatian_number")),
        ):
            if value:
                field = fields_by_name.get(field_name)
                identifier_candidates.append((field_name, value, field.confidence if field else None))
        best_identifier = max(
            identifier_candidates,
            key=lambda item: item[2] if item[2] is not None else -1,
            default=None,
        )

        def queue_parcel_association_review(reason: str, confidence: Optional[float]):
            existing_case = db.query(VerificationCase).filter(
                VerificationCase.document_id == document_id,
                VerificationCase.case_type == "parcel_association_review",
                VerificationCase.status.in_([VerificationStatus.PENDING, VerificationStatus.IN_REVIEW]),
            ).first()
            if not existing_case:
                confidence_note = f" Identifier confidence: {confidence:.0%}." if confidence is not None else " Identifier confidence is unavailable."
                db.add(VerificationCase(
                    document_id=document_id,
                    case_type="parcel_association_review",
                    priority="high",
                    status=VerificationStatus.PENDING,
                    summary=f"{reason}{confidence_note} Confirm the parcel association before linking this document.",
                    confidence=confidence,
                    submitted_by=current_user.id,
                    state=trusted_state,
                district=trusted_district,
                tehsil=trusted_tehsil,
                village=trusted_village,
                ))
            update_document_status(db, document_id, ProcessingStatus.HUMAN_REVIEW_REQUIRED)
            db.commit()
            log_action(
                db=db,
                action="PARCEL_ASSOCIATION_REVIEW_REQUIRED",
                entity_type="document",
                entity_id=document_id,
                user_id=current_user.id,
                details=reason,
            )
            return {
                "status": "review_required",
                "document_id": document_id,
                "document_type": doc.document_type.value if hasattr(doc.document_type, "value") else str(doc.document_type),
                "page_count": doc.page_count,
                "fields_extracted": len([field for field in saved_fields if field.value]),
                "parcel_id": None,
                "parcel_code": None,
                "reason": reason,
            }

        if not best_identifier or best_identifier[2] is None or best_identifier[2] < 0.70:
            reason = "No survey, khasra, plot, or khata identifier was extracted with the minimum 70% confidence."
            return queue_parcel_association_review(reason, best_identifier[2] if best_identifier else None)

        selected_identifier = best_identifier[0]
        selected_identifier_confidence = best_identifier[2]
        # Extracted area is normalized to acres by the extraction workflow.
        if current_area_val is not None:
            area_unit_str = "acres"
        area_confidence = fields_by_name.get("area").confidence if fields_by_name.get("area") else None
        trusted_area = current_area_val if area_confidence is not None and area_confidence >= 0.70 else None
        owner_field_name = "owner_name" if field_dict.get("owner_name") else "new_owner"
        owner_field = fields_by_name.get(owner_field_name)
        trusted_owner = owner_name if owner_field and owner_field.confidence is not None and owner_field.confidence >= 0.70 else None
        land_class_field = fields_by_name.get("land_classification")
        trusted_land_class = land_class if land_class_field and land_class_field.confidence is not None and land_class_field.confidence >= 0.70 else None

        try:
            parcel = resolve_or_create_parcel(
                db=db,
                survey_no=survey_val if selected_identifier == "survey_number" else None,
                khasra_no=khasra_val if selected_identifier == "khasra_number" else None,
                plot_no=plot_val if selected_identifier == "plot_number" else None,
                khata_no=khata_val if selected_identifier in ("khata_number", "khatian_number") else None,
                village=trusted_village,
                district=trusted_district,
                state=trusted_state,
                document_id=document_id,
                current_area=trusted_area,
                area_unit=area_unit_str,
                land_classification=trusted_land_class,
                current_owner=trusted_owner,
                identifier_confidence=selected_identifier_confidence,
            )
        except ParcelResolutionNeedsReview as exc:
            return queue_parcel_association_review(str(exc), selected_identifier_confidence)

        # Link Owner if extracted
        if trusted_owner:
            existing_owner = (
                db.query(Owner)
                .filter(Owner.parcel_id == parcel.id, Owner.name == owner_name)
                .first()
            )
            if not existing_owner:
                new_owner = Owner(
                    parcel_id=parcel.id,
                    name=trusted_owner,
                    normalized_name=field_dict.get("owner_name") or trusted_owner,
                    father_husband_name=field_dict.get("father_husband_name"),
                    is_current="true",
                    ownership_share="1.0",
                    source_document_id=document_id,
                    confidence=owner_field.confidence,
                )
                db.add(new_owner)

        # Link Mutation if extracted
        mut_no_field = fields_by_name.get("mutation_number")
        mut_no = field_dict.get("mutation_number") if mut_no_field and mut_no_field.confidence is not None and mut_no_field.confidence >= 0.70 else None
        if mut_no:
            existing_mut = db.query(Mutation).filter(Mutation.mutation_number == mut_no).first()
            if not existing_mut:
                mut = Mutation(
                    parcel_id=parcel.id,
                    source_document_id=document_id,
                    mutation_number=mut_no,
                    mutation_date=field_dict.get("mutation_date"),
                    previous_owner=field_dict.get("previous_owner"),
                    new_owner=field_dict.get("new_owner") or owner_name,
                    area=current_area_val,
                )
                db.add(mut)

        # Link Registration if extracted
        reg_no_field = fields_by_name.get("registration_number")
        reg_no = field_dict.get("registration_number") if reg_no_field and reg_no_field.confidence is not None and reg_no_field.confidence >= 0.70 else None
        if reg_no:
            existing_reg = db.query(Registration).filter(Registration.registration_number == reg_no).first()
            if not existing_reg:
                reg = Registration(
                    parcel_id=parcel.id,
                    source_document_id=document_id,
                    registration_number=reg_no,
                    registration_date=field_dict.get("registration_date"),
                    registration_type="Sale Deed" if "sale" in lower_text else "Registration",
                )
                db.add(reg)

        # Step 6: Route Low-Confidence / Uncertain OCR to Human Verification Queue
        avg_ocr_conf = total_ocr_confidence / max(len(image_paths), 1)
        uncertain_fields = [f for f in saved_fields if f.value and (f.confidence or 0) < 0.70]
        critical_uncertain = [f for f in uncertain_fields if f.field_name in ("owner_name", "area", "survey_number", "plot_number", "khasra_number")]

        if avg_ocr_conf < 0.70 or uncertain_fields:
            existing_case = db.query(VerificationCase).filter(
                VerificationCase.document_id == document_id,
                VerificationCase.status == VerificationStatus.PENDING
            ).first()
            if not existing_case:
                field_names_str = ", ".join([f.field_name for f in uncertain_fields]) if uncertain_fields else "Low document OCR confidence"
                v_case = VerificationCase(
                    parcel_id=parcel.id,
                    document_id=document_id,
                    case_type="low_confidence_ocr_review",
                    priority="high" if critical_uncertain else "medium",
                    status=VerificationStatus.PENDING,
                    summary=f"Uncertain OCR extractions requiring verification in {doc.original_filename}: [{field_names_str}]",
                    confidence=round(avg_ocr_conf, 3),
                )
                db.add(v_case)
                logger.info(f"Queued human verification case for low-confidence OCR in doc {doc.id[:8]}")

        # A completed OCR/extraction run can still require a human decision.
        # Keep that state visible in the document record so queues and clients
        # do not treat uncertain extraction as fully verified work.
        requires_human_review = avg_ocr_conf < 0.70 or bool(uncertain_fields)
        final_status = (
            ProcessingStatus.HUMAN_REVIEW_REQUIRED
            if requires_human_review
            else ProcessingStatus.COMPLETED
        )
        update_document_status(db, document_id, final_status)
        db.commit()

        populated_fields_count = len([f for f in saved_fields if f.value])
        log_action(
            db=db,
            action="PROCESSED",
            entity_type="document",
            entity_id=document_id,
            user_id=current_user.id if current_user else "system",
            details=f"Extracted {populated_fields_count} active fields, linked to parcel {parcel.parcel_code}",
        )

        return {
            "status": "review_required" if requires_human_review else "success",
            "document_id": document_id,
            "document_type": doc.document_type.value if hasattr(doc.document_type, "value") else str(doc.document_type),
            "classification_confidence": doc.classification_confidence,
            "page_count": doc.page_count,
            "fields_extracted": populated_fields_count,
            "parcel_id": parcel.id,
            "parcel_code": parcel.parcel_code,
        }

    except Exception as e:
        logger.error(f"Processing failed for document {document_id}: {e}", exc_info=True)
        # Recover the SQLAlchemy session before trying to persist FAILED;
        # after a database error its transaction may otherwise reject commit.
        db.rollback()
        update_document_status(
            db,
            document_id,
            ProcessingStatus.FAILED,
            error="Processing failed. Retry the document or contact an administrator.",
        )
        raise HTTPException(
            status_code=500,
            detail="Document processing failed. Check its status and retry, or contact an administrator.",
        )


@router.get("/{document_id}/extracted-data")
async def get_document_extracted_data(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get full extraction results, OCR text blocks, and evidence items for a document.
    Used by frontend Document Inspection & Evidence modal.
    """
    doc = get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    from backend.security.authorization import authorize_document_access
    authorize_document_access(doc, current_user, "read", db)

    # Fetch extracted fields
    fields = (
        db.query(ExtractedField)
        .filter(ExtractedField.document_id == document_id)
        .order_by(ExtractedField.field_name.asc())
        .all()
    )

    # Fetch OCR results
    ocr_results = (
        db.query(OcrResult)
        .filter(OcrResult.document_id == document_id)
        .order_by(OcrResult.page_number.asc())
        .all()
    )

    # Fetch Evidence
    evidence_items = (
        db.query(Evidence)
        .filter(Evidence.document_id == document_id)
        .all()
    )

    # Linked parcel if any
    from backend.models.parcel import ParcelDocument, Parcel
    parcel_link = (
        db.query(ParcelDocument)
        .filter(ParcelDocument.document_id == document_id)
        .first()
    )
    parcel_info = None
    if parcel_link:
        parcel = db.query(Parcel).filter(Parcel.id == parcel_link.parcel_id).first()
        if parcel:
            from backend.security.authorization import authorize_parcel_access
            try:
                authorize_parcel_access(parcel, current_user, "read", db)
                parcel_info = {
                    "id": parcel.id,
                    "parcel_code": parcel.parcel_code,
                    "ulpin": parcel.ulpin,
                    "village": parcel.village,
                    "tehsil": parcel.tehsil,
                    "district": parcel.district,
                    "state": parcel.state,
                    "current_area": parcel.current_area,
                    "area_unit": parcel.area_unit,
                    "current_owner": parcel.current_owner,
                    "verification_status": parcel.verification_status,
                }
            except HTTPException:
                parcel_info = {"restricted": True}

    association_case = db.query(VerificationCase).filter(
        VerificationCase.document_id == document_id,
        VerificationCase.case_type == "parcel_association_review",
        VerificationCase.status.in_([VerificationStatus.PENDING, VerificationStatus.IN_REVIEW]),
    ).order_by(VerificationCase.created_at.desc()).first()

    combined_ocr_text = "\n".join([r.text for r in ocr_results if r.text])

    return {
        "document": {
            "id": doc.id,
            "filename": doc.original_filename,
            "document_type": doc.document_type.value if hasattr(doc.document_type, "value") else str(doc.document_type),
            "processing_status": doc.processing_status.value if hasattr(doc.processing_status, "value") else str(doc.processing_status),
            "file_size": doc.file_size,
            "file_hash": doc.file_hash,
            "mime_type": doc.mime_type,
            "page_count": doc.page_count,
            "language": doc.language,
            "upload_timestamp": doc.upload_timestamp.isoformat() if doc.upload_timestamp else None,
            "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
        },
        "parcel": parcel_info,
        "parcel_association_review": {
            "id": association_case.id,
            "status": association_case.status.value if association_case and hasattr(association_case.status, "value") else (str(association_case.status) if association_case else None),
            "reason": association_case.summary if association_case else None,
            "confidence": association_case.confidence if association_case else None,
        } if association_case else None,
        "ocr_text": combined_ocr_text,
        "extracted_fields": [
            {
                "id": f.id,
                "field_name": f.field_name,
                "value": f.value,
                "normalized_value": f.normalized_value,
                "english_value": getattr(f, "english_value", None),
                "language": getattr(f, "language", "English"),
                "confidence": f.confidence if f.value else 0.0,
                "status": f.status.value if hasattr(f.status, "value") else str(f.status),
                "extraction_method": f.extraction_method,
                "page_number": f.page_number,
                "bbox": f.bbox,
                "raw_text": f.raw_text,
            }
            for f in fields
        ],
        "ocr_blocks": [
            {
                "id": o.id,
                "page_number": o.page_number,
                "text": o.text,
                "confidence": o.confidence,
                "bbox": o.bbox,
                "block_type": o.block_type,
            }
            for o in ocr_results
        ],
        "evidence_items": [
            {
                "id": e.id,
                "field_name": e.field_name,
                "value": e.value,
                "page_number": e.page_number,
                "ocr_confidence": e.ocr_confidence,
                "extraction_confidence": e.extraction_confidence,
                "description": e.description,
            }
            for e in evidence_items
        ],
    }
