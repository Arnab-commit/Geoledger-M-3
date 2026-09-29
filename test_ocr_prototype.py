"""
Test script for verifying enhanced OCR, Preprocessing, and Field Extraction on real documents.
"""
import os
import re
import cv2
import numpy as np
import fitz
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def extract_all_revenue_fields(text: str) -> dict:
    extracted = {}
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    noise_words = {
        'DOCUMENT', 'INFORMATION', 'PAGE', 'SECTION', 'DETAILS', 'RECORD',
        'AUTHENTICATION', 'CERTIFICATE', 'SAMPLE', 'DEMONSTRATION', 'LAND',
        'REVENUE', 'DEPARTMENT', 'GOVERNMENT', 'LOCAL', 'ADDRESS',
        'PREVIOUS SHARE', 'NEW SHARE', 'SHARE', 'FATHER\'S NAME', 'OWNER', 'DATE'
    }

    table_header_words = {
        'PREVIOUS SHARE', 'NEW SHARE', 'SHARE', 'FATHER\'S NAME', 'OWNER',
        'SL NO', 'SERIAL NO', 'PERCENTAGE', 'PERCENT', 'RELATION'
    }

    # Step 1: Multi-line / Structured Key-Value Label Parser
    label_dict = {
        'mutation_number': [
            r'^(?:Mutation\s+Application\s+No\.?|Mutation\s+Case\s+No\.?|Mutation\s+No\.?|Case\s+No\.?|Mut(?:ation)?\s*No\.?)$',
            r'^(?:नामांतरण\s*सं\.?|दाखिल\s*खारिज\s*संख्या|মিউটেশন\s*কেস\s*নং)$'
        ],
        'registration_number': [
            r'^(?:Registration\s+No\.?|Reg\s+No\.?|Deed\s+No\.?|Sale\s+Deed\s+No\.?|Registered\s+Sale\s+Deed\s+No\.?)$',
            r'^(?:पंजीकरण\s*सं\.?|बैनामा\s*सं\.?|দলিল\s*নং)$'
        ],
        'survey_number': [
            r'^(?:Survey\/Khasra\s+No\.?|Survey\s+No\.?|Survey\s+Number|Khasra\/Survey\s+No\.?|Plot\s*\/\s*Survey\s*No\.?)$',
            r'^(?:खसरा\/सर्वे\s*नं\.?|सर्वे\s*संख्या)$'
        ],
        'khasra_number': [
            r'^(?:Survey\/Khasra\s+No\.?|Khasra\s+No\.?|Khasra\s+Number|Khasra)$',
            r'^(?:खसरा\s*नं\.?|खसरा\s*संख्या)$'
        ],
        'plot_number': [
            r'^(?:Plot\/Dag\s+No\.?|Plot\s+No\.?|Plot\s+Number|Dag\s+No\.?|Dag\s+Number)$',
            r'^(?:प्लॉट\s*नं\.?|दाग\s*নং|দাগ\s*নম্বর)$'
        ],
        'khata_number': [
            r'^(?:Khata\/Khatiyan\s+No\.?|Khata\s+No\.?|Khata\s+Number|Khatian\s+No\.?|Khatiyan\s+No\.?)$',
            r'^(?:खाता\s*संख्या|খতিয়ান\s*নং)$'
        ],
        'khatian_number': [
            r'^(?:Khata\/Khatiyan\s+No\.?|Khatian\s+No\.?|Khatiyan\s+No\.?)$',
            r'^(?:খতিয়ান\s*নং|খতিয়ান)$'
        ],
        'patta_number': [
            r'^(?:Patta\s+No\.?|Patta\s+Number)$',
            r'^(?:पट्टा\s*संख्या|পাট্টা\s*নং)$'
        ],
        'village': [
            r'^(?:Village\/Mouza|Village|Mouza|Location)$',
            r'^(?:ग्राम\/मौजा|ग्राम|मौजा|গ্রাম|মৌজা)$'
        ],
        'mouza': [
            r'^(?:Village\/Mouza|Mouza)$',
            r'^(?:मौजा|মৌজা)$'
        ],
        'district': [
            r'^(?:District|Dist\.?)$',
            r'^(?:जिला|জেলা)$'
        ],
        'state': [
            r'^(?:State)$',
            r'^(?:राज्य|রাজ্য)$'
        ],
        'tehsil': [
            r'^(?:Subdivision|Sub-Division|Block|Tehsil|Taluk|Taluka|Police\s*Station|Police\s*Station\s*\/\s*Block)$',
            r'^(?:तहसील|ब्लॉक|অঞ্চল|ব্লক)$'
        ],
        'area': [
            r'^(?:Recorded\s+Area|Total\s+Area|Area\s+of\s+Land|Area|Plot\s+Area)$',
            r'^(?:रकबा|क्षेत्रफल|জমির\s*পরিমাণ)$'
        ],
        'area_unit': [
            r'^(?:Area\s+Unit|Unit)$',
            r'^(?:इकाई|একক)$'
        ],
        'land_classification': [
            r'^(?:Land\s+Classification|Land\s+Class|Type\s+of\s+Land|Classification)$',
            r'^(?:भूमि\s*प्रकार|জমির\s*শ্রেণী)$'
        ],
        'registration_date': [
            r'^(?:Date\s+of\s+Execution|Date\s+of\s+Registration|Registration\s+Date|Execution\s+Date)$',
            r'^(?:पंजीकरण\s*दिनांक|তারেখ)$'
        ],
        'mutation_date': [
            r'^(?:Date\s+of\s+Mutation|Mutation\s+Date)$',
            r'^(?:नामांतरण\s*दिनांक)$'
        ],
        'owner_name': [
            r'^(?:Recorded\s+Owner|Present\s+Owner|Landowner|Owner\s+Name|Name\s+of\s+Owner|Owner)$',
            r'^(?:खातेदार\s*का\s*नाम|भूस्वामी|মালিকের\s*নাম)$'
        ],
        'previous_owner': [
            r'^(?:Present\s+Owner\s*\/\s*Executant\s*\/\s*Vendor|Previous\s+Owner|Seller|Vendor)$',
            r'^(?:पूर्व\s*मालिक|বিক্রেতা)$'
        ],
        'new_owner': [
            r'^(?:Purchaser\s*\/\s*Transferee|Purchaser|Transferee|New\s+Owner|Buyer|Current\s+Owner)$',
            r'^(?:क्रेता|নতুন\s*মালিক|ক্রেতা)$'
        ],
        'father_husband_name': [
            r'^(?:Father\'?s?\s+Name|Husband\'?s?\s+Name|Father\/Husband\s+Name)$',
            r'^(?:पिता\s*का\s*नाम|पति\s*का\s*नाम|পিতার\s*নাম)$'
        ]
    }

    # Line-by-line adjacency parser
    for i in range(len(lines) - 1):
        line = lines[i]
        next_line = lines[i+1]
        for field, patterns in label_dict.items():
            if field in extracted:
                continue
            for pat in patterns:
                if re.match(pat, line, re.IGNORECASE):
                    # Check next line isn't another label or table header
                    is_another_label = any(re.match(p, next_line, re.IGNORECASE) for pl in label_dict.values() for p in pl)
                    is_table_header = next_line.upper() in table_header_words
                    if not is_another_label and not is_table_header:
                        val = next_line.strip()
                        if val.upper() not in noise_words and len(val) > 0:
                            extracted[field] = val
                            break

    # Step 2: In-line regex patterns
    inline_patterns = {
        'mutation_number': [
            r'(?:Mutation\s+(?:Application|Case|Order)?\s*No\.?|Case\s*No\.?|MUT\s*No\.?)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'\b(MUT\/[A-Za-z0-9\/-]+|MC\/[0-9]{4}\/[0-9]+)\b',
            r'(?:नामांतरण\s*सं\.?|दाखिल\s*खारिज\s*संख्या)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'(?:মিউটেশন\s*কেস\s*নং)[\s.:#]+([A-Za-z0-9\/-]+)'
        ],
        'registration_number': [
            r'(?:REGISTERED\s+SALE\s+DEED\s+NO|Registration\s+No\.?|Reg\s+No\.?|Deed\s+No\.?|Deed\s+Number)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'\b(REG\/[A-Za-z0-9\/-]+|DEED\/[0-9]{4}\/[0-9]+)\b',
            r'(?:पंजीकरण\s*सं\.?|बैनामा\s*सं\.?|দলিল\s*নং)[\s.:#]+([A-Za-z0-9\/-]+)'
        ],
        'survey_number': [
            r'(?:Plot\s*\/\s*Survey\s*No\.?|Survey\s*No\.?|Survey\s*Number|Khasra\/Survey\s*No\.?)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)',
            r'(?:खसरा\/सर्वे\s*नं\.?|सर्वे\s*संख्या)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)'
        ],
        'khasra_number': [
            r'(?:Survey\/Khasra\s*No\.?|Khasra\s*No\.?|Khasra\s*Number|Khasra)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)',
            r'(?:खसरा\s*नं\.?|खसरा\s*संख्या)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)'
        ],
        'plot_number': [
            r'(?:Plot\s*\/Dag\s*No\.?|Plot\s*No\.?|Plot\s*Number|Dag\s*No\.?|Dag\s*Number)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)',
            r'(?:প্লট\s*নং|দাগ\s*নং|দাগ\s*নম্বর)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)'
        ],
        'khata_number': [
            r'(?:Khata\s*\/Khatiyan\s*No\.?|Khata\s*No\.?|Khata\s*Number|Khata)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)',
            r'(?:खाता\s*संख्या)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)'
        ],
        'khatian_number': [
            r'(?:Khata\s*\/Khatiyan\s*No\.?|Khatian\s*No\.?|Khatiyan\s*No\.?|Khatian|Khatiyan)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)',
            r'(?:খতিয়ান\s*নং|খতিয়ান)[\s.:#]+([0-9]+[A-Za-z0-9\/-]*)'
        ],
        'patta_number': [
            r'(?:Patta\s*No\.?|Patta\s*Number)[\s.:#]+([A-Za-z0-9\/-]+)',
            r'(?:पट्टा\s*संख्या|পাট্টা\s*নং)[\s.:#]+([A-Za-z0-9\/-]+)'
        ],
        'village': [
            r'(?:Village\s*\/\s*Mouza|Mouza\s*\/\s*Village|Village|Location)[\s:]+([A-Za-z\s]+?)(?:,|\n|District|Tehsil|Sub-Division|Police|JL|$)',
            r'(?:situated\s+at\s+Village\s+([A-Za-z\s]+?)(?:,|\n|Mouza|District|$))',
            r'(?:ग्राम|गाँव)[\s:]+([^\n,]+)'
        ],
        'mouza': [
            r'(?:Mouza\s*\/\s*Village|Village\s*\/\s*Mouza|Mouza)[\s:]+([A-Za-z\s]+?)(?:,|\n|District|Tehsil|Sub-Division|Police|JL|$)',
            r'(?:situated\s+at\s+(?:Village\s+[A-Za-z\s]+?,\s*)?Mouza\s+([A-Za-z\s]+?)(?:,|\n|District|$))',
            r'(?:মৌজা)[\s:]+([^\n,]+)'
        ],
        'district': [
            r'(?:District|Dist\.?)[\s:]+([A-Za-z\s]+?)(?:,|\n|State|Sub-Division|Tehsil|Police|$)',
            r'(?:District\s+([A-Za-z\s]+?)(?:,|\n|West\s+Bengal|State|$))',
            r'(?:जिला|জেলা)[\s:]+([^\n,]+)'
        ],
        'state': [
            r'(?:State)[\s:]+([A-Za-z\s]+?)(?:,|\n|District|$)',
            r'(?:GOVERNMENT\s+OF\s+([A-Za-z\s]+?)(?:\s*-|\s+LAND|\n))',
            r'\b(West\s+Bengal|Uttar\s+Pradesh|Maharashtra|Bihar|Karnataka|Gujarat|Rajasthan|Madhya\s+Pradesh|Odisha|Tamil\s+Nadu)\b',
            r'(?:राज्य|রাজ্য)[\s:]+([^\n,]+)'
        ],
        'tehsil': [
            r'(?:Sub-Division|Subdivision|Block|Police\s*Station\s*\/\s*Block|Tehsil|Taluk|Taluka)[\s:]+([A-Za-z0-9\s-]+?)(?:,|\n|District|Mouza|Village|$)',
            r'(?:तहसील|ब्लॉक|थाना|ব্লক)[\s:]+([^\n,]+)'
        ],
        'area': [
            r'(?:total\s+recorded\s+area\s+of\s+(?:approximately\s+)?|having\s+a\s+total\s+recorded\s+area\s+of\s+(?:approximately\s+)?|Area\s+of\s+Land|Total\s+Area|Area|Plot\s+Area|Recorded\s+Area)[\s:]*([\d.]+)\s*(?:Acres?|Acre|Hectares?|Ha|Bigha|Sq\.?ft|Sq\.?m|Guntas?|Cents?|acre)?',
            r'(?:रकबा|क्षेत्रफल|জমির\s*পরিমাণ)[\s:]+([\d.]+)'
        ],
        'area_unit': [
            r'(?:total\s+recorded\s+area\s+of\s+(?:approximately\s+)?[\d.]+\s*|having\s+a\s+total\s+recorded\s+area\s+of\s+(?:approximately\s+)?[\d.]+\s*|Area\s+of\s+Land[\s:]+[\d.]+\s*|Total\s+Area[\s:]+[\d.]+\s*|Area[\s:]+[\d.]+\s*|Recorded\s+Area[\s:]+[\d.]+\s*)(Acres?|Acre|Hectares?|Ha|Bigha|Sq\.?ft|Sq\.?m|Guntas?|Cents?|acre)',
            r'(?:एकड़|हेक्टेयर|বিঘা|একর)'
        ],
        'owner_name': [
            r'(?:Recorded\s+Owner|Present\s+Owner\s*\/\s*Executant\s*\/\s*Vendor|Landowner|Owner\s+Name|Name\s+of\s+Owner|recorded\s+in\s+the\s+name\s+of\s+(?:Mr\.?|Mrs\.?|Ms\.?|Shri\s*)?|Owner)[\s:]+([A-Za-z\s.]+?)(?:,|\n|under|Father|Husband|Survey|Plot|Area|$)',
            r'(?:खातेदार\s*का\s*नाम|भूस्वामी\s*का\s*नाम|মালিকের\s*নাম)[\s:]+([^\n,]+)'
        ],
        'previous_owner': [
            r'(?:Present\s+Owner\s*\/\s*Executant\s*\/\s*Vendor|Previous\s+Owner|Seller|Vendor|Former\s+Owner)[\s:]+([A-Za-z\s.]+?)(?:,|\n|Purchaser|Transferee|New\s+Owner|Buyer|$)',
            r'(?:पूर्व\s*मालिक|বিক্রেতা)[\s:]+([^\n,]+)'
        ],
        'new_owner': [
            r'(?:Purchaser\s*\/\s*Transferee|Purchaser|Transferee|New\s+Owner|Buyer|Current\s+Owner)[\s:]+([A-Za-z\s.]+?)(?:,|\n|Consideration|Father|Area|Survey|$)',
            r'(?:क्रेता|নতুন\s*মালিক|ক্রেতা)[\s:]+([^\n,]+)'
        ],
        'father_husband_name': [
            r'(?:Father\'?s?\s+Name|Husband\'?s?\s+Name|W\/o|S\/o|D\/o)[\s:]+([A-Za-z\s.]+?)(?:,|\n|Total|Share|Survey|Plot|Area|$)',
            r'(?:पिता\s*का\s*नाम|पति\s*का\s*नाम|পিতার\s*নাম)[\s:]+([^\n,]+)'
        ],
        'land_classification': [
            r'(?:Land\s+Classification|Land\s+Class|Classification|Type\s+of\s+Land)[\s:]+([A-Za-z\s()]+?)(?:,|\n|$)',
            r'(?:भूमि\s*प्रकार|জমির\s*শ্রেণী)[\s:]+([^\n,]+)'
        ],
        'registration_date': [
            r'(?:Date\s+of\s+Execution|Date\s+of\s+Registration|Registration\s+Date|Execution\s+Date)[\s:]+([0-9]{1,2}[\/\.-][0-9]{1,2}[\/\.-][0-9]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})',
        ],
        'mutation_date': [
            r'(?:Date\s+of\s+Mutation|Mutation\s+Date)[\s:]+([0-9]{1,2}[\/\.-][0-9]{1,2}[\/\.-][0-9]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})',
        ]
    }

    for field, patterns in inline_patterns.items():
        if field in extracted and extracted[field]:
            continue
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                val = match.group(1) if match.groups() else match.group(0)
                val = val.strip().strip(',').strip()
                if val and val.upper() not in noise_words and len(val) > 0:
                    extracted[field] = val
                    break

    # Step 3: Table / Section Parser for Previous / New Owners
    prev_match = re.search(r'Previous\s+Owner\(?s?\)?\s*\n+Owner\s*\n+Father\'s\s+Name\s*\n+Previous\s+Share\s*\n+([A-Za-z\s]+?)\n+([A-Za-z\s.]+?)\n', text, re.IGNORECASE)
    if prev_match:
        extracted['previous_owner'] = prev_match.group(1).strip()
        fath = prev_match.group(2).strip()
        if fath and fath != '—' and fath.upper() not in noise_words:
            extracted['father_husband_name'] = fath

    new_match = re.search(r'New\s+Owner\(?s?\)?\s*\n+Owner\s*\n+Father\'s\s+Name\s*\n+New\s+Share\s*\n+([A-Za-z\s]+?)\n', text, re.IGNORECASE)
    if new_match:
        extracted['new_owner'] = new_match.group(1).strip()

    # Step 4: Generic date fallback
    if 'mutation_date' not in extracted and 'registration_date' not in extracted:
        date_match = re.search(r'(?:Date|Dated)[\s.:#\n]+([0-9]{1,2}[\/\.-][0-9]{1,2}[\/\.-][0-9]{2,4}|[0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4}|[A-Za-z]+\s+[0-9]{1,2},?\s+[0-9]{4})', text, re.IGNORECASE)
        if date_match:
            extracted['mutation_date'] = date_match.group(1).strip()

    # Step 5: Area Unit fallback
    if 'area' in extracted and 'area_unit' not in extracted:
        if 'acre' in text.lower():
            extracted['area_unit'] = 'Acres'
        elif 'hectare' in text.lower() or 'ha' in text.lower():
            extracted['area_unit'] = 'Hectares'
        elif 'bigha' in text.lower():
            extracted['area_unit'] = 'Bigha'
        elif 'sq' in text.lower():
            extracted['area_unit'] = 'Sq Ft'

    # Step 6: Canonical owner fallback
    if 'owner_name' not in extracted:
        if 'new_owner' in extracted:
            extracted['owner_name'] = extracted['new_owner']
        elif 'previous_owner' in extracted:
            extracted['owner_name'] = extracted['previous_owner']

    # Clean any accidental noise
    for k in list(extracted.keys()):
        val = extracted[k]
        if not val or val.upper() in noise_words:
            del extracted[k]

    return extracted

def run_test():
    # 1. WhatsApp image
    img_path = r"uploads\originals\ee4fc5e7-a9bc-44d8-ae7e-269de47d2862.jpeg"
    if os.path.exists(img_path):
        img = Image.open(img_path)
        t1 = pytesseract.image_to_string(img, lang="eng+hin+ben")
        r1 = extract_all_revenue_fields(t1)
        print("=== WhatsApp Image Extracted Fields ===")
        for k, v in sorted(r1.items()):
            print(f"  {k:22}: {v}")

    # 2. PDF Document
    pdf_path = r"uploads\originals\5a13b918-fbbf-4854-b71e-2e56a8856203.pdf"
    if os.path.exists(pdf_path):
        doc = fitz.open(pdf_path)
        t2 = "\n".join([p.get_text() for p in doc])
        r2 = extract_all_revenue_fields(t2)
        print("\n=== Professional Mutation PDF Extracted Fields ===")
        for k, v in sorted(r2.items()):
            print(f"  {k:22}: {v}")

if __name__ == "__main__":
    run_test()
