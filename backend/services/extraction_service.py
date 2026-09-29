"""Structured land-record field extraction service supporting English, Hindi, Bengali, Marathi, Gujarati, Tamil, Telugu, Kannada, Malayalam, Odia, Punjabi, and Urdu records."""

import logging
import re
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from backend.models.document import Document
from backend.models.extraction import ExtractedField, FieldStatus, FieldAuditHistory
from backend.models.ocr import OcrResult
from backend.services.normalization_service import (
    convert_indic_digits,
    normalize_area,
    normalize_date,
    normalize_identifier,
    normalize_name,
    get_english_representation,
    get_script_language_name,
)

logger = logging.getLogger("geoldger.extraction")

# Field definitions from master specification
LAND_RECORD_FIELDS = [
    "owner_name",
    "father_husband_name",
    "co_owner",
    "survey_number",
    "khasra_number",
    "plot_number",
    "khata_number",
    "khatian_number",
    "village",
    "mouza",
    "tehsil",
    "block",
    "district",
    "state",
    "area",
    "area_unit",
    "land_classification",
    "ownership_type",
    "mutation_number",
    "mutation_date",
    "previous_owner",
    "new_owner",
    "registration_number",
    "registration_date",
    "boundary_details",
]

NOISE_WORDS = {
    'DOCUMENT', 'INFORMATION', 'PAGE', 'SECTION', 'DETAILS', 'RECORD',
    'AUTHENTICATION', 'CERTIFICATE', 'SAMPLE', 'DEMONSTRATION', 'LAND',
    'REVENUE', 'DEPARTMENT', 'GOVERNMENT', 'LOCAL', 'ADDRESS',
    'PREVIOUS SHARE', 'NEW SHARE', 'SHARE', "FATHER'S NAME", 'OWNER', 'DATE',
    'ORDER', 'REMARKS', 'OFFICIAL', 'SEAL', 'SIGNATURE', '—', '-', 'N/A', 'NONE'
}

TABLE_HEADER_WORDS = {
    'PREVIOUS SHARE', 'NEW SHARE', 'SHARE', "FATHER'S NAME", 'OWNER',
    'SL NO', 'SERIAL NO', 'PERCENTAGE', 'PERCENT', 'RELATION', 'FATHER NAME'
}


def extract_fields_from_text(text: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract structured revenue fields from OCR text using multi-strategy analysis:
    1. Multi-line Form & Label-Value adjacency parsing
    2. Tabular ownership matrix parsing
    3. Continuous narrative / sentence extraction
    4. Comprehensive multilingual (15 Indic languages + English) in-line regex pattern recognition
    """
    extracted: Dict[str, Dict[str, Any]] = {}
    if not text:
        return {f: {"value": None, "confidence": 0.0, "method": "rule_based", "status": FieldStatus.MISSING, "raw_text": None} for f in LAND_RECORD_FIELDS}

    # Clean zero-width spaces/joiners and Unicode non-breaking spaces that break regex matching
    text = (
        text.replace('‌', '')  # Zero-Width Non-Joiner (ZWNJ)
            .replace('‍', '')  # Zero-Width Joiner (ZWJ)
            .replace('﻿', '')  # BOM
            .replace(' ', ' ') # Non-breaking space
    )

    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # Helper function to register extracted field
    def set_field(name: str, val: str, raw: str, conf: float = 0.88, method: str = "form_layout"):
        if not val:
            return
        val = str(val).strip().strip(',').strip(';').strip('.')
        if not val or val.upper() in NOISE_WORDS:
            return
        if name not in extracted or extracted[name].get("confidence", 0) < conf:
            extracted[name] = {
                "value": val,
                "confidence": conf,
                "method": method,
                "status": FieldStatus.CONFIRMED,
                "raw_text": raw[:120] if raw else val,
            }

    # Strategy 1: Multi-line Label -> Value Adjacency Parser (Form Layout)
    label_dict = {
        'mutation_number': [
            r'^(?:Mutation\s+Application\s+No\.?|Mutation\s+Case\s+No\.?|Mutation\s+No\.?|Case\s+No\.?|Mut(?:ation)?\s*No\.?)$',
            r'^(?:नामांतरण\s*सं\.?|दाखिल\s*खारिज\s*संख्या|फेरफार\s*क्र\.?|মিউটেশন\s*কেস\s*নং|ફેરફાર\s*નંબર|ઇન્તકાલ\s*નંબર|ఇంతకాల్\s*నంబరు|ഇന്തക്കാൽ\s*നമ്പർ)$'
        ],
        'registration_number': [
            r'^(?:Registration\s+No\.?|Reg\s+No\.?|Deed\s+No\.?|Sale\s+Deed\s+No\.?|Registered\s+Sale\s+Deed\s+No\.?)$',
            r'^(?:पंजीकरण\s*सं\.?|बैनामा\s*सं\.?|दस्ताऐवज\s*क्र\.?|দলিল\s*নং|દસ્તાવેજ\s*નંબર|பத்திர\s*எண்|రిజిస్ట్రేషన్\s*నంబరు|ನೋಂದಣಿ\s*ಸಂಖ್ಯೆ|ആധാര\s*നമ്പർ|রেজিস্ট্রেশন\s*ନଂ)$'
        ],
        'survey_number': [
            r'^(?:Survey\/Khasra\s+No\.?|Survey\s+No\.?|Survey\s+Number|Khasra\/Survey\s+No\.?|Plot\s*\/\s*Survey\s*No\.?)$',
            r'^(?:खसरा\/सर्वे\s*नं\.?|सर्वे\s*संख्या|सर्व्हे\s*क्र\.?|গট\s*নং|સર્વે\s*નંબર|புல\s*எண்|సర్వే\s*నంబరు|ಸರ್ವೆ\s*ನಂಬರ್|സർവേ\s*നമ്പർ|ସର୍ଭେ\s*ନଂ)$'
        ],
        'khasra_number': [
            r'^(?:Survey\/Khasra\s+No\.?|Khasra\s+No\.?|Khasra\s+Number|Khasra)$',
            r'^(?:खसरा\s*नं\.?|खसरा\s*संख्या|खसरा\s*नंबर|ਖਸਰਾ\s*ਨੰਬਰ|خسرہ\s*نمبر)$'
        ],
        'plot_number': [
            r'^(?:Plot\/Dag\s+No\.?|Plot\s+No\.?|Plot\s+Number|Dag\s+No\.?|Dag\s+Number|Gat\s+No\.?)$',
            r'^(?:प्लॉट\s*नं\.?|गट\s*क्र\.?|দাগ\s*নং|দাগ\s*নম্বর|দাগ|પ્લોટ\s*નંબર|പ്ലോട്ട്\s*നമ്പർ|ପ୍ଲଟ୍\s*ନଂ)$'
        ],
        'khata_number': [
            r'^(?:Khata\/Khatiyan\s+No\.?|Khata\s+No\.?|Khata\s+Number|Khatian\s+No\.?|Khatiyan\s+No\.?)$',
            r'^(?:खाता\s*संख्या|खाते\s*क्र\.?|খতিয়ান\s*নং|ખાતા\s*નંબર|ఖాతా\s*నంబరు|ಖಾತಾ\s*ನಂಬರ್|കരം\s*നമ്പർ|ଖାତା\s*ନଂ|کھاتہ\s*نمبر)$'
        ],
        'khatian_number': [
            r'^(?:Khata\/Khatiyan\s+No\.?|Khatian\s+No\.?|Khatiyan\s+No\.?)$',
            r'^(?:খতিয়ান\s*নং|খতিয়ান|खतियान|ଖତିୟାନ\s*ନଂ)$'
        ],
        'patta_number': [
            r'^(?:Patta\s+No\.?|Patta\s+Number)$',
            r'^(?:पट्टा\s*संख्या|পাট্টা\s*নং|பட்டா\s*எண்|పట్టా\s*నంబరు|ಪಟ್ಟಾ\s*ನಂಬರ್|പട്ടാ\s*നമ്പർ|ପଟ୍ଟା\s*ନଂ)$'
        ],
        'village': [
            r'^(?:Village\/Mouza|Village|Mouza|Location)$',
            r'^(?:ग्राम\/मौजा|ग्राम|मौजा|गाव|গ্রাম|মৌজা|ગામ|கிராமம்|గ్రామం|ಗ್ರಾಮ|വില്ലേജ്|ଗ୍ରାମ|ਪਿੰਡ|موضع)$'
        ],
        'mouza': [
            r'^(?:Village\/Mouza|Mouza)$',
            r'^(?:मौजा|মৌজা|మౌజా)$'
        ],
        'district': [
            r'^(?:District|Dist\.?)$',
            r'^(?:जिला|जिल्हा|জেলা|જિલ્લો|மாவட்டம்|జిల్లా|ಜಿಲ್ಲೆ|ജില്ല|ଜିଲ୍ଲା|ਜ਼ਿਲ੍ਹਾ|ضلع)$'
        ],
        'state': [
            r'^(?:State)$',
            r'^(?:राज्य|রাজ্য|રાજ્ય|மாநிலம்|రాష్ట్రం|ರಾಜ್ಯ|സംസ്ഥാനം|ରାଜ୍ୟ|ਸੂਬਾ|ریاست)$'
        ],
        'tehsil': [
            r'^(?:Subdivision|Sub-Division|Tehsil|Taluk|Taluka|Police\s*Station)$',
            r'^(?:तहसील|तालुका|অঞ্চল|તાલુકો|வட்டம்|మండలం|ತಾಲೂಕು|താലൂക്ക്|ତହସିଲ|ਤਹਿਸੀਲ|تحصیل)$'
        ],
        'block': [
            r'^(?:Block|Development\s+Block|CD\s+Block)$',
            r'^(?:ब्लॉक|ব্লক|બ્લોક|வளர்ச்சி\s*வட்டம்)$'
        ],
        'area': [
            r'^(?:Recorded\s+Area|Total\s+Area|Area\s+of\s+Land|Area|Plot\s+Area)$',
            r'^(?:रकबा|क्षेत्रफल|क्षेत्र|জমির\s*পরিমাণ|ક્ષેત્રફળ|விஸ்தீரணம்|విస్తీర్ణం|ವಿಸ್ತೀರ್ಣ|വിസ്തീർണ്ണം|କ୍ଷେତ୍ରଫଳ|ਰਕਬਾ|رقبہ)$'
        ],
        'area_unit': [
            r'^(?:Area\s+Unit|Unit)$',
            r'^(?:इकाई|एकक|একক|યુનિટ|அலகு|యూనిట్|ಪ್ರಮಾಣ|യൂണിറ്റ്|ମାପ)$'
        ],
        'land_classification': [
            r'^(?:Land\s+Classification|Land\s+Class|Type\s+of\s+Land|Classification)$',
            r'^(?:भूमि\s*प्रकार|जमिनीचा\s*प्रकार|জমির\s*শ্রেণী|જમીનનો\s*પ્રકાર|நில\s*வகைப்பாடு|భూమి\s*రకం|ಭೂಮಿ\s*ವರ್ಗೀಕರಣ|ഭൂമി\s*തരം|ଜମି\s*କିସମ)$'
        ],
        'ownership_type': [
            r'^(?:Ownership\s+Type|Type\s+of\s+Ownership|Tenure(?:\s+Type)?)$',
            r'^(?:स्वामित्व\s*प्रकार|মালিকানার\s*ধরন|માલિકીનો\s*પ્રકાર|உரிமை\s*வகை|యాజమాన్య\s*రకం|ಮಾಲೀಕತ್ವದ\s*ಪ್ರಕಾರ)$'
        ],
        'registration_date': [
            r'^(?:Date\s+of\s+Execution|Date\s+of\s+Registration|Registration\s+Date|Execution\s+Date)$',
            r'^(?:पंजीकरण\s*दिनांक|दस्त\s*दिनांक|তারিখ|નોંધણી\s*તારીખ|பதிவு\s*தேதி|రిజిస్ట్రేషన్\s*తేదీ|ನೋಂದಣಿ\s*ದಿನಾಂಕ|രജിസ്ട്രേഷൻ\s*തീയതി)$'
        ],
        'mutation_date': [
            r'^(?:Date\s+of\s+Mutation|Mutation\s+Date)$',
            r'^(?:नामांतरण\s*दिनांक|फेरफार\s*दिनांक|মিউটেশন\s*তারিখ)$'
        ],
        'owner_name': [
            r'^(?:Recorded\s+Owner|Present\s+Owner|Landowner|Owner\s+Name|Name\s+of\s+Owner|Owner)$',
            r'^(?:खातेदार\s*का\s*नाम|खातेदाराचे\s*नाव|भूस्वामी|মালিকের\s*নাম|ખાતેદારનું\s*નામ|உரிமையாளர்\s*பெயர்|పట్టాదారు\s*పేరు|ಮಾಲೀಕರ\s*ಹೆಸರು|ഉടമസ്ഥന്റെ\s*പേര്|ଜମି\s*ମାଲିକ|ਮਾਲਕ\s*ਦਾ\s*ਨਾਮ|مالک)$'
        ],
        'previous_owner': [
            r'^(?:Present\s+Owner\s*\/\s*Executant\s*\/\s*Vendor|Previous\s+Owner|Seller|Vendor)$',
            r'^(?:पूर्व\s*मालिक|जुना\s*मालक|विक्रेता|বিক্রেতা|વેચનાર|விற்பனையாளர்|విక్రేత|ಮಾರಾಟಗಾರ|വിൽപ്പനക്കാരൻ|ବିକ୍ରେତା|فروخت\s*کنندە)$'
        ],
        'new_owner': [
            r'^(?:Purchaser\s*\/\s*Transferee|Purchaser|Transferee|New\s+Owner|Buyer|Current\s+Owner)$',
            r'^(?:क्रेता|नवीन\s*मालक|নতুন\s*মালিক|ক্রেতা|ખરીદનાર|வாங்குபவர்|కొనుగోలుదారు|ಖರೀದಿದಾರ|വാങ്ങുന്നയാൾ|କ୍ରେତା|خریدار)$'
        ],
        'father_husband_name': [
            r'^(?:Father\'?s?\s+Name|Husband\'?s?\s+Name|Father\/Husband\s+Name)$',
            r'^(?:पिता\s*का\s*नाम|पति\s*का\s*नाम|वडिलांचे\s*नाव|পিতার\s*নাম|પિતાનું\s*નામ|தகப்பனார்\s*பெயர்|తండ్రి\s*పేరు|ತಂದೆಯ\s*ಹೆಸರು|പിതാവിന്റെ\s*പേര്|ବାପାଙ୍କ\s*ନାମ|ਪਿਤਾ\s*ਦਾ\s*ਨਾਮ|والد\s*کا\s*نام)$'
        ]
    }

    for i in range(len(lines) - 1):
        line = lines[i]
        next_line = lines[i+1]
        for field, patterns in label_dict.items():
            if field in extracted:
                continue
            for pat in patterns:
                if re.match(pat, line, re.IGNORECASE):
                    is_another_label = any(re.match(p, next_line, re.IGNORECASE) for pl in label_dict.values() for p in pl)
                    is_table_header = next_line.upper() in TABLE_HEADER_WORDS
                    if not is_another_label and not is_table_header:
                        val = next_line.strip()
                        if val.upper() not in NOISE_WORDS and len(val) > 0:
                            set_field(field, val, f"{line} -> {next_line}", conf=0.92, method="form_label_layout")
                            break

    # Strategy 2: Inline Key-Value Colon & Multilingual Regex Recognition
    inline_patterns = {
        'mutation_number': [
            r'(?:Mutation\s+(?:Application|Case|Order)?\s*No\.?|Case\s*No\.?|MUT\s*No\.?)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'\b(MUT\/[A-Za-z0-9\/-]+|MC\/[0-9]{4}\/[0-9]+)\b',
            r'(?:नामांतरण\s*सं\.?|दाखिल\s*खारिज\s*संख्या|फेरफार\s*क्र\.?)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'(?:মিউটেশন\s*কেস\s*নং|ફેરફાર\s*નંબર)[\s.:#]+([A-Za-z0-9\/-]+)'
        ],
        'registration_number': [
            r'(?:REGISTERED\s+SALE\s+DEED\s+NO|Registration\s+No\.?|Reg\s+No\.?|Deed\s+No\.?|Deed\s+Number)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'\b(REG\/[A-Za-z0-9\/-]+|DEED\/[0-9]{4}\/[0-9]+|AP\/REG\/[0-9]{4}\/[0-9]+|DEED\/WB\/[0-9]{4}\/[0-9]+)\b',
            r'(?:पंजीकरण\s*सं(?:ख्या|\.)?|पंजीयन\s*सं(?:ख्या|\.)?|बैनामा\s*सं(?:ख्या|\.)?|दस्ताऐवज\s*क्र(?:मांक|\.)?|দলিল\s*(?:নং|নম্বর)|দললি\s*(?:নং|নম্বর)|রেজিস্ট্রেশন\s*(?:নং|নম্বর)|દસ્તાવેજ\s*નંબર|નોંધણી\s*નંબર|ஆவண\s*எண்|பத்திர\s*எண்|பதிவு\s*எண்|பஜிவு\s*எண்|ரிజిస్ట్రేషన్\s*నంబరు|రిజిన్ట్రేషన్\s*నంబరు|దస్తావేజు\s*నంబరు|ನೋಂದಣಿ\s*ಸಂಖ್ಯೆ|ದಸ್ತಾವೇಜು\s*ಸಂಖ್ಯೆ|ആധാര\s*നമ്പർ|രജിസ്ട്രേഷൻ\s*നമ്പർ|ରେଜିଷ୍ଟ୍ରେସନ\s*ନଂ|ଦଲିଲ\s*ନଂ)[\s.:#]+([A-Za-z0-9\/-]+)'
        ],
        'survey_number': [
            r'(?:Plot\s*\/\s*Survey\s*No\.?|Survey\s*No\.?|Survey\s*Number|Khasra\/Survey\s*No\.?)[\s.:#]+([0-9०-९০-৯૦-૯੦-੯୦-୯௦-௯౦-౯೦-೯൦-൯]+[A-Za-z0-9\/-]*)',
            r'(?:खसरा\/सर्वे\s*नं\.?|सर्वे\s*संख्या|सर्व्हे\s*क्र(?:मांक|\.)?|সার্ভে\s*(?:নং|নম্বর)|গট\s*নং|સર્વે\s*નંબર|புல\s*எண்|சர்வே\s*எண்|సర్వే\s*నంబరు|053\s*నంబరు|సర్ప\s*నంబరు|ಸರ್ವೆ\s*ನಂಬರ್|സർവേ\s*നമ്പർ|ସର୍ଭେ\s*ନଂ)[\s.:#]+([0-9०-९০-৯]+[A-Za-z0-9\/-]*)'
        ],
        'khasra_number': [
            r'(?:Survey\/Khasra\s*No\.?|Khasra\s*No\.?|Khasra\s*Number|Khasra)[\s.:#]+([0-9०-९০-৯]+[A-Za-z0-9\/-]*)',
            r'(?:खसरा\s*नं\.?|खसरा\s*संख्या|ਖਸਰਾ\s*ਨੰਬਰ|خسرہ\s*نمبر)[\s.:#]+([0-9०-९]+[A-Za-z0-9\/-]*)'
        ],
        'plot_number': [
            r'(?:Plot\s*\/Dag\s*No\.?|Plot\s*No\.?|Plot\s*Number|Dag\s*No\.?|Dag\s*Number|Gat\s*No\.?)[\s.:#]+([0-9०-९০-৯]+[A-Za-z0-9\/-]*)',
            r'(?:प्लॉट\s*नं\.?|गट\s*क्र\.?|দাগ\s*নং|দাগ\s*নম্বর|দাগ|દાખ\s*નંબર|પ્લોટ\s*નંબર|பிளாட்\s*எண்|ప్లాట్\s*నంబరు|പ്ലോട്ട്\s*നമ്പർ|ପ୍ଲଟ୍\s*ନଂ)[\s.:#]+([0-9०-९০-৯૦-૯੦-੯୦-୯௦-௯౦-౯೦-೯൦-൯]+[A-Za-z0-9\/-]*)'
        ],
        'khata_number': [
            r'(?:Khata\s*\/Khatiyan\s*No\.?|Khata\s*No\.?|Khata\s*Number|Khata)[\s.:#\n,]+([0-9०-९০-৯]+[A-Za-z0-9\/-]*)',
            r'(?:खाता\s*संख्या|खाते\s*क्र\.?|খতিয়ান\s*নং|ખાતા\s*નંબર|ఖాతా\s*నంబరు)[\s.:#\n,]+([0-9०-९০-৯]+[A-Za-z0-9\/-]*)'
        ],
        'khatian_number': [
            r'(?:Khata\s*\/Khatiyan\s*No\.?|Khatian\s*No\.?|Khatiyan\s*No\.?|Khatian|Khatiyan)[\s.:#\n,]+([0-9०-९০-৯]+[A-Za-z0-9\/-]*)',
            r'(?:under\s+)?Khatian[,\s\n]+(?:No\.?|Number)?[\s.:#]*([0-9०-९০-৯]+[A-Za-z0-9\/-]*)',
            r'(?:খতিয়ান\s*নং|খতিয়ান|খতিয়ান\s*নং|খতিয়ান|खतियान|ଖତିୟାନ\s*ନଂ)[\s.:#\n,]+([0-9০-৯୦-୯]+[A-Za-z0-9\/-]*)'
        ],
        'village': [
            r'(?:Village\s*\/\s*Mouza|Mouza\s*\/\s*Village|Village|Location)[\s:]+([^\n,;]{2,40}?)(?:,|\n|District|Tehsil|Sub-Division|Police|JL|$)',
            r'(?:situated\s+at\s+Village\s+([A-Za-z\s]+?)(?:,|\n|Mouza|District|$))',
            r'(?:ग्राम|गाँव|गाव|গ্রাম|মৌজা|গাঁও|ગામ|கிராமம்|கரிகாமம்|கரிாமம்|గ్రామం|గ్[ీత]మం|ಗ್ರಾಮ|വില്ലേജ്|ଗ୍ରାମ|ମୌଜା|ਪਿੰਡ)[\s:]+([^\n,]+)'
        ],
        'mouza': [
            r'(?:Mouza\s*\/\s*Village|Village\s*\/\s*Mouza|Mouza)[\s:]+([^\n,;]{2,40}?)(?:,|\n|District|Tehsil|Sub-Division|Police|JL|$)',
            r'(?:situated\s+at\s+(?:Village\s+[A-Za-z\s]+?,\s*)?Mouza\s+([A-Za-z\s]+?)(?:,|\n|District|$))',
            r'(?:मौजा|মৌজা|మౌజా)[\s:]+([^\n,]+)'
        ],
        'district': [
            r'(?:District|Dist\.?)[\s:]+([^\n,;]{2,40}?)(?:,|\n|State|Sub-Division|Tehsil|Police|$)',
            r'(?:District\s+([A-Za-z\s]+?)(?:,|\n|West\s+Bengal|State|$))',
            r'(?:जिला|जिल्हा|জেলা|জলিা|જિલ્લો|மாவட்டம்|மாவடடம்|ஜిల్లా|జిల్ల|జిల్లా|ಜಿಲ್ಲೆ|ജില്ല|ଜିଲ୍ଲା|ਜ਼ਿਲ੍ਹਾ|ضلع)[\s:]+([^\n,]+)'
        ],
        'state': [
            r'(?:State)[\s:]+([^\n,;]{2,40}?)(?:,|\n|District|$)',
            r'(?:GOVERNMENT\s+OF\s+([A-Za-z\s]+?)(?:\s*-|\s+LAND|\n))',
            r'\b(West\s+Bengal|WEST\s+BENGA|Uttar\s+Pradesh|Maharashtra|Bihar|Karnataka|Gujarat|Rajasthan|Madhya\s+Pradesh|Odisha|Tamil\s+Nadu|TAMIL\s+NADU|Punjab|Haryana|Kerala|Telangana|Andhra\s+Pradesh|ANDHRA\s+PRADESH)\b',
            r'(?:राज्य|রাজ্য|રાજ્ય|மாநிலம்|ராష్ట్రం|ರಾಜ್ಯ|സംസ്ഥാനം|ରାଜ୍ୟ|ਸੂਬਾ)[\s:]+([^\n,]+)'
        ],
        'tehsil': [
            r'(?:Sub-Division|Subdivision|Tehsil|Taluk|Taluka|Police\s*Station)[\s:]+([^\n,;]{2,40}?)(?:,|\n|District|Mouza|Village|$)',
            r'(?:तहसील|तालुका|थाना|તાલુકો|வட்டம்|మండలం|ತಾಲೂಕು|താലൂക്ക്|ତହସିଲ|ਤਹਿਸੀਲ|تحصیل)[\s:]+([^\n,]+)'
        ],
        'block': [
            r'(?:Development\s+Block|CD\s+Block|Block)[\s:]+([^\n,;]{2,50}?)(?:,|\n|District|Tehsil|Taluk|Village|$)',
            r'(?:ब्लॉक|ব্লক|બ્લોક|வளர்ச்சி\s*வட்டம்)[\s:]+([^\n,]+)'
        ],
        'area': [
            r'(?:total\s+recorded\s+area\s+of\s+(?:approximately\s+)?|having\s+a\s+total\s+recorded\s+area\s+of\s+(?:approximately\s+)?|Area\s+of\s+Land|Total\s+Area|Area|Plot\s+Area|Recorded\s+Area)[\s:]*([\d.]+|[०-९০-৯૦-૯.]+)\s*(?:Acres?|Acre|Hectares?|Ha|Bigha|Sq\.?ft|Sq\.?m|Guntas?|Cents?|Gunthas?|Kanal|Marla|acre)?',
            r'(?:रकबा|क्षेत्रफल|क्षेत्र|জমির\s*পরিমাণ|ક્ષેત્રફળ|விஸ்தீரணம்|విస్తీర్ణం|ವಿಸ್ತೀರ್ಣ|വിസ്തീർണ്ണം|କ୍ଷେତ୍ରଫଳ|ਰਕਬਾ|رقبہ)[\s:]+([\d.]+|[०-९০-৯૦-૯.]+)'
        ],
        'area_unit': [
            r'(?:total\s+recorded\s+area\s+of\s+(?:approximately\s+)?[\d.]+\s*|having\s+a\s+total\s+recorded\s+area\s+of\s+(?:approximately\s+)?[\d.]+\s*|Area\s+of\s+Land[\s:]+[\d.]+\s*|Total\s+Area[\s:]+[\d.]+\s*|Area[\s:]+[\d.]+\s*|Recorded\s+Area[\s:]+[\d.]+\s*)(Acres?|Acre|Hectares?|Ha|Bigha|Sq\.?ft|Sq\.?m|Guntas?|Gunthas?|Cents?|Kanal|Marla|acre)',
            r'(?:एकड़|हेक्टेयर|हेक्टर|बीघा|বিঘা|একর|হেক্টর|વીઘા|ગુંઠા|गुंठा|गुंठे|சென்ட்|సెంట్లు|സെന്റ്|ਏਕੜ|ਬੀਘਾ)'
        ],
        'owner_name': [
            r'(?:Recorded\s+Owner|Present\s+Owner\s*\/\s*Executant\s*\/\s*Vendor|Landowner|Owner\s+Name|Name\s+of\s+Owner|recorded\s+in\s+the\s+name\s+of\s+(?:Mr\.?|Mrs\.?|Ms\.?|Shri\s*)?|Owner)[\s:]+([^\n,;]{2,50}?)(?:,|\n|under|Father|Husband|Survey|Plot|Area|$)',
            r'(?:खातेदार\s*का\s*नाम|खातेदाराचे\s*नाव|भूस्वामी\s*का\s*नाम|মালিকের\s*নাম|মালিক|খতিয়ানদার|ખાતેદારનું\s*નામ|உரிமையாளர்\s*பெயர்|பட்டாதாரர்\s*பெயர்|உரிமையாளர்|பாரி\s*பெயர்|பட்டாதாரர்|பट्टाதாரர்|పట్టాదారు\s*పేరు|భూయజమాని\s*పేరు|పట్టాదారు|భూయజమాని|ಮಾಲೀಕರ\s*ಹೆಸರು|ಪಟ್ಟೇದಾರರ\s*ಹೆಸರು|ഉടമസ്ഥന്റെ\s*പേര്|ଜମି\s*ମାଲିକ|ପଟ୍ଟାଦାର|ਮਾਲਕ\s*ਦਾ\s*ਨਾਮ|مالک\s*کا\s*نام)[\s:]+([^\n,]+)'
        ],
        'previous_owner': [
            r'(?:Present\s+Owner\s*\/\s*Executant\s*\/\s*Vendor|Previous\s+Owner|Seller|Vendor|Former\s+Owner)[\s:]+([^\n,;]{2,50}?)(?:,|\n|Purchaser|Transferee|New\s+Owner|Buyer|$)',
            r'(?:पूर्व\s*मालिक|जुना\s*मालक|विक्रेता|বিক্রেতা|વેચનાર|விற்பனையாளர்|విక్రేత|ಮಾರಾಟಗಾರ|വിൽപ്പനക്കാരൻ|ବିକ୍ରେତା)[\s:]+([^\n,]+)'
        ],
        'new_owner': [
            r'(?:Purchaser\s*\/\s*Transferee|Purchaser|Transferee|New\s+Owner|Buyer|Current\s+Owner)[\s:]+([^\n,;]{2,50}?)(?:,|\n|Consideration|Father|Area|Survey|$)',
            r'(?:क्रेता|नवीन\s*मालक|নতুন\s*মালিক|ক্রেতা|ખરીદનાર|வாங்குபவர்|కొనుగోలుదారు|ಖರೀದಿದಾರ|വാങ്ങുന്നയാൾ|କ୍ରେତା)[\s:]+([^\n,]+)'
        ],
        'father_husband_name': [
            r'(?:Father\'?s?\s+Name|Husband\'?s?\s+Name|W\/o|S\/o|D\/o)[\s:]+([^\n,;]{2,50}?)(?:,|\n|Total|Share|Survey|Plot|Area|$)',
            r'(?:पिता\s*का\s*नाम|पति\s*का\s*नाम|वडिलांचे\s*नाव|পিতার\s*নাম|স্বামীর\s*নাম|পিতা|પિતાનું\s*નામ|தகப்பனார்\s*பெயர்|தந்தை\s*பெயர்|తండ్రి\s*పేరు|ತಂದೆಯ\s*ಹೆಸರು|പിതാവിന്റെ\s*പേര്|ବାପାଙ୍କ\s*ନାମ|ਪਿਤਾ\s*ਦਾ\s*ਨਾਮ|والد\s*کا\s*نام)[\s:]+([^\n,]+)'
        ],
        'land_classification': [
            r'(?:Land\s+Classification|Land\s+Class|Classification|Type\s+of\s+Land)[\s:]+([^\n,;]{2,50}?)(?:,|\n|$)',
            r'(?:भूमि\s*प्रकार|जमिनीचा\s*प्रकार|জমির\s*শ্রেণী|જમીનનો\s*પ્રકાર|நில\s*வகைப்பாடு|భూమి\s*రకం|ಭೂಮಿ\s*ವರ್ಗೀಕರಣ|ഭൂമി\s*തരം|ଜମି\s*କିସମ)[\s:]+([^\n,]+)'
        ],
        'ownership_type': [
            r'(?:Ownership\s+Type|Type\s+of\s+Ownership|Tenure(?:\s+Type)?)[\s:]+([^\n,;]{2,50}?)(?:,|\n|$)',
            r'(?:स्वामित्व\s*प्रकार|মালিকানার\s*ধরন|માલિકીનો\s*પ્રકાર|உரிமை\s*வகை|యాజమాన్య\s*రకం|ಮಾಲೀಕತ್ವದ\s*ಪ್ರಕಾರ)[\s:]+([^\n,]+)'
        ],
        'registration_date': [
            r'(?:Date\s+of\s+Execution|Date\s+of\s+Registration|Registration\s+Date|Execution\s+Date)[\s:]+([0-9०-९০-৯]{1,2}[\/\.-][0-9०-९০-৯]{1,2}[\/\.-][0-9०-९০-৯]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})',
        ],
        'mutation_date': [
            r'(?:Date\s+of\s+Mutation|Mutation\s+Date)[\s:]+([0-9०-९০-৯]{1,2}[\/\.-][0-9०-९০-৯]{1,2}[\/\.-][0-9०-९০-৯]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})',
        ],
        'boundary_details': [
            r'(?:Boundary\s+Details|Boundaries)[\s:]+([\s\S]+?)(?:\n\n|Present\s+Owner|Purchaser|$)',
            r'(?:चौहद्दी|सीमा\s*विवरण|ચતુર્સીમા|எல்லை\s*விவரங்கள்)[\s:]+([^\n]+)'
        ]
    }

    for field, patterns in inline_patterns.items():
        if field in extracted and extracted[field].get("confidence", 0) >= 0.85:
            continue
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                val = match.group(1) if match.groups() else match.group(0)
                set_field(field, val, match.group(0), conf=0.88, method="inline_regex")
                break

    # Strategy 3: Tabular Multi-Party Ownership Matrix Extraction
    prev_match = re.search(r'Previous\s+Owner\(?s?\)?\s*\n+Owner\s*\n+Father\'s\s+Name\s*\n+Previous\s+Share\s*\n+([A-Za-z\s]+?)\n+([A-Za-z\s.]+?)\n', text, re.IGNORECASE)
    if prev_match:
        set_field('previous_owner', prev_match.group(1).strip(), prev_match.group(0), conf=0.95, method="table_parser")
        fath = prev_match.group(2).strip()
        if fath and fath != '—' and fath.upper() not in NOISE_WORDS:
            set_field('father_husband_name', fath, prev_match.group(0), conf=0.90, method="table_parser")

    new_match = re.search(r'New\s+Owner\(?s?\)?\s*\n+Owner\s*\n+Father\'s\s+Name\s*\n+New\s+Share\s*\n+([A-Za-z\s]+?)\n', text, re.IGNORECASE)
    if new_match:
        set_field('new_owner', new_match.group(1).strip(), new_match.group(0), conf=0.95, method="table_parser")

    # Strategy 4: Fallback Date Detection
    if 'mutation_date' not in extracted and 'registration_date' not in extracted:
        date_match = re.search(r'(?:Date|Dated|दिनांक|তারিখ)[\s.:#\n]+([0-9०-९]{1,2}[\/\.-][0-9०-९]{1,2}[\/\.-][0-9०-९]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})', text, re.IGNORECASE)
        if date_match:
            set_field('mutation_date', date_match.group(1).strip(), date_match.group(0), conf=0.75, method="date_heuristic")

    # Strategy 5: Area Unit Inference
    if 'area' in extracted and 'area_unit' not in extracted:
        lower_t = text.lower()
        if 'acre' in lower_t or 'एकर' in text or 'એકર' in text or 'ஏக்கர்' in text or 'ఎకరాలు' in text:
            set_field('area_unit', 'Acres', 'inferred', conf=0.80, method="unit_heuristic")
        elif 'hectare' in lower_t or 'हेक्टेयर' in text or 'হেক্টর' in text or 'હેક્ટર' in text or 'ha' in lower_t:
            set_field('area_unit', 'Hectares', 'inferred', conf=0.80, method="unit_heuristic")
        elif 'bigha' in lower_t or 'बीघा' in text or 'বিঘা' in text or 'વીઘા' in text:
            set_field('area_unit', 'Bigha', 'inferred', conf=0.80, method="unit_heuristic")
        elif 'guntha' in lower_t or 'गुंठा' in text or 'गुंठे' in text or 'ગુંઠા' in text:
            set_field('area_unit', 'Gunthas', 'inferred', conf=0.80, method="unit_heuristic")
        elif 'cent' in lower_t or 'சென்ட்' in text or 'సెంట్లు' in text:
            set_field('area_unit', 'Cents', 'inferred', conf=0.80, method="unit_heuristic")
        elif 'sq' in lower_t or 'square' in lower_t:
            set_field('area_unit', 'Sq.ft', 'inferred', conf=0.80, method="unit_heuristic")

    # Canonical owner mapping if only new/previous owner was extracted
    if 'owner_name' not in extracted:
        if 'new_owner' in extracted:
            set_field('owner_name', extracted['new_owner']['value'], extracted['new_owner']['raw_text'], conf=0.85, method="owner_inference")
        elif 'previous_owner' in extracted:
            set_field('owner_name', extracted['previous_owner']['value'], extracted['previous_owner']['raw_text'], conf=0.80, method="owner_inference")

    # Fill in any missing fields with empty values
    for field in LAND_RECORD_FIELDS:
        if field not in extracted:
            extracted[field] = {
                "value": None,
                "confidence": 0.0,
                "method": "rule_based",
                "status": FieldStatus.MISSING,
                "raw_text": None,
            }

    return extracted


def save_extracted_fields(
    db: Session,
    document_id: str,
    extracted_fields: Dict[str, Dict[str, Any]],
    page_number: int = 1,
) -> List[ExtractedField]:
    """Save extracted fields to database with automated normalization."""
    # Upsert by field name so reprocessing does not orphan field history or erase
    # officer corrections/final verification values.
    existing_fields = {
        field.field_name: field
        for field in db.query(ExtractedField).filter(ExtractedField.document_id == document_id).all()
    }

    saved_fields = []

    for field_name, data in extracted_fields.items():
        val = data.get("value")
        norm_val = val
        english_val = None
        lang_name = "English"

        # Automatic field-specific normalization and transliteration
        if val:
            english_val = get_english_representation(val, field_name)
            lang_name = get_script_language_name(val)
            if field_name in ("owner_name", "previous_owner", "new_owner", "father_husband_name", "co_owner"):
                norm_val, _ = normalize_name(val)
            elif field_name in ("survey_number", "khasra_number", "plot_number", "khata_number", "khatian_number", "registration_number", "mutation_number"):
                norm_val, _ = normalize_identifier(val)
            elif field_name in ("registration_date", "mutation_date"):
                norm_val, _ = normalize_date(val)
            elif field_name == "area":
                norm_acres, _, _ = normalize_area(val, extracted_fields.get("area_unit", {}).get("value"))
                norm_val = str(norm_acres) if norm_acres is not None else val

        conf = data.get("confidence", 0.0) if val else 0.0
        status_val = data.get("status", FieldStatus.CONFIRMED if val else FieldStatus.MISSING)
        if not val:
            status_val = FieldStatus.MISSING

        field = existing_fields.get(field_name)
        previous_ai_value = field.ai_extracted_value if field else None
        if field is None:
            field = ExtractedField(document_id=document_id, field_name=field_name)
            db.add(field)

        field.ai_extracted_value = val
        effective_value = field.final_verified_value or field.officer_corrected_value or val
        field.value = effective_value
        field.normalized_value = norm_val if effective_value == val else effective_value
        field.english_value = english_val if effective_value == val else get_english_representation(effective_value, field_name)
        field.language = lang_name if effective_value == val else get_script_language_name(effective_value)
        field.confidence = conf
        field.page_number = page_number
        field.extraction_method = data.get("method", "rule_based")
        field.status = FieldStatus.CONFIRMED if (field.officer_corrected_value or field.final_verified_value) else status_val
        field.raw_text = data.get("raw_text")
        db.flush()

        # Keep a durable AI extraction version for initial and changed reprocessed values.
        if previous_ai_value != val:
            db.add(FieldAuditHistory(
                field_id=field.id,
                document_id=document_id,
                field_name=field_name,
                stage="AI_EXTRACTED",
                value=val,
                changed_by="SYSTEM_AI",
                reason="Automated extraction" if previous_ai_value is None else "Reprocessed source document",
            ))
        saved_fields.append(field)

    db.commit()
    logger.info(f"Saved {len(saved_fields)} extracted fields for document {document_id}")
    return saved_fields
