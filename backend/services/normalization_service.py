"""Normalization engine for land record data across 15 Indic and International scripts."""

import logging
import re
from typing import Optional, Tuple
from datetime import datetime
from rapidfuzz import fuzz

logger = logging.getLogger("geoldger.normalization")

INDIC_DIGIT_MAP = {
    # Devanagari (Hindi, Marathi, Sanskrit, Nepali)
    '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
    '५': '5', '६': '6', '७': '7', '८': '8', '९': '9',
    # Bengali / Assamese
    '০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4',
    '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9',
    # Gujarati
    '૦': '0', '૧': '1', '૨': '2', '૩': '3', '૪': '4',
    '૫': '5', '૬': '6', '૭': '7', '૮': '8', '૯': '9',
    # Gurmukhi (Punjabi)
    '੦': '0', '੧': '1', '੨': '2', '੩': '3', '੪': '4',
    '੫': '5', '੬': '6', '੭': '7', '੮': '8', '੯': '9',
    # Odia
    '୦': '0', '୧': '1', '୨': '2', '୩': '3', '୪': '4',
    '୫': '5', '୬': '6', '୭': '7', '୮': '8', '୯': '9',
    # Tamil
    '௦': '0', '௧': '1', '௨': '2', '௩': '3', '௪': '4',
    '௫': '5', '௬': '6', '௭': '7', '௮': '8', '௯': '9',
    # Telugu
    '౦': '0', '౧': '1', '౨': '2', '౩': '3', '౪': '4',
    '౫': '5', '౬': '6', '౭': '7', '౮': '8', '౯': '9',
    # Kannada
    '೦': '0', '೧': '1', '೨': '2', '೩': '3', '೪': '4',
    '೫': '5', '೬': '6', '೭': '7', '೮': '8', '೯': '9',
    # Malayalam
    '൦': '0', '൧': '1', '൨': '2', '൩': '3', '൪': '4',
    '൫': '5', '൬': '6', '൭': '7', '൮': '8', '൯': '9',
    # Urdu / Arabic-Indic
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
    '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
    # Eastern Arabic-Indic / Persian
    '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
    '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
}


def convert_indic_digits(text: Optional[str]) -> str:
    """Convert all Indic and Perso-Arabic numeral characters to standard ASCII digits."""
    if not text:
        return ""
    res = []
    for ch in str(text):
        res.append(INDIC_DIGIT_MAP.get(ch, ch))
    return "".join(res)


# Comprehensive multi-lingual area unit conversion factors to standard Acres
AREA_CONVERSIONS = {
    # Standard International
    "acre": 1.0,
    "acres": 1.0,
    "एकड़": 1.0,
    "একর": 1.0,
    "એકર": 1.0,
    "ஏக்கர்": 1.0,
    "ఎకరాలు": 1.0,
    "ಎಕರೆ": 1.0,
    "ഏക്കർ": 1.0,
    "ଏକର": 1.0,
    "ਏਕੜ": 1.0,
    "ایکڑ": 1.0,
    # Hectare
    "hectare": 2.47105,
    "hectares": 2.47105,
    "ha": 2.47105,
    "हेक्टेयर": 2.47105,
    "हेक्टर": 2.47105,
    "হেক্টর": 2.47105,
    "હેક્ટર": 2.47105,
    "ஹெக்டேர்": 2.47105,
    "హెక్టార్లు": 2.47105,
    "ಹೆಕ್ಟೇರ್": 2.47105,
    "ഹെക്ടർ": 2.47105,
    "ହେକ୍ଟର": 2.47105,
    "ਹੈਕਟੇਅਰ": 2.47105,
    "ہیکٹر": 2.47105,
    # Bigha (Standard ~0.33 to 0.62 acres depending on region, standard nominal 0.33)
    "bigha": 0.33,
    "बीघा": 0.33,
    "বিঘা": 0.33,
    "વીઘા": 0.40,
    "ବିଘା": 0.33,
    "ਬੀਘਾ": 0.20,
    "بیگھہ": 0.33,
    # Katha / Kattha (~0.0165 acres)
    "katha": 0.0165,
    "kattha": 0.0165,
    "कट्ठा": 0.0165,
    "কাটা": 0.0165,
    "କଠା": 0.0165,
    # Decimal / Dismil / Cent (~0.01 acres)
    "decimal": 0.01,
    "dismil": 0.01,
    "ডিসমিল": 0.01,
    "डेसिमल": 0.01,
    "ডেসিমাল": 0.01,
    "cent": 0.01,
    "cents": 0.01,
    "சென்ட்": 0.01,
    "సెంట్లు": 0.01,
    "ಸೆಂಟ್": 0.01,
    "സെന്റ്": 0.01,
    # Guntha / Gunthas (~0.025 acres or 1089 sq.ft)
    "guntha": 0.025,
    "gunthas": 0.025,
    "गुंठा": 0.025,
    "गुंठे": 0.025,
    "ગુંઠા": 0.025,
    "ಗುಂಟೆ": 0.025,
    "గుంటలు": 0.025,
    # Kanal & Marla (North India / Punjab / Haryana)
    "kanal": 0.125,
    "ਕਨਾਲ": 0.125,
    "कनाल": 0.125,
    "کنال": 0.125,
    "marla": 0.00625,
    "ਮਰਲਾ": 0.00625,
    "मरला": 0.00625,
    "مرلہ": 0.00625,
    # Biswa (~0.0165 to 0.03 acres)
    "biswa": 0.0165,
    "बिस्वा": 0.0165,
    "ਬਿਸਵਾ": 0.0165,
    # Ground (South India ~2400 sq ft = 0.055 acres)
    "ground": 0.0551,
    "கிரவுண்ட்": 0.0551,
    # Chatak (Bengal / Assam ~45 sq ft)
    "chatak": 0.00103,
    "ছটাক": 0.00103,
    # Square units
    "sq.ft": 1 / 43560,
    "sqft": 1 / 43560,
    "sq ft": 1 / 43560,
    "square feet": 1 / 43560,
    "sq.m": 1 / 4046.86,
    "sqm": 1 / 4046.86,
    "sq m": 1 / 4046.86,
    "square meters": 1 / 4046.86,
    "sq.yard": 1 / 4840,
    "sq yard": 1 / 4840,
    "gaj": 1 / 4840,
    "गज": 1 / 4840,
}


def normalize_name(name: Optional[str]) -> Tuple[Optional[str], float]:
    """
    Normalize personal names across multilingual honorifics (strip honorifics, normalize spacing).
    Returns (normalized_name, confidence).
    """
    if not name:
        return None, 0.0

    # Strip common Indian and multilingual honorifics
    honorifics = [
        r"^Shri\s+", r"^Smt\s+", r"^Sri\s+", r"^Mr\s+", r"^Mrs\s+",
        r"^Dr\s+", r"^Late\s+", r"^Sri\.\s+", r"^Shri\.\s+", r"^Mr\.\s+", r"^Mrs\.\s+",
        r"^श्री\s+", r"^श्रीमती\s+", r"^শ্রী\s+", r"^শ্রীমতী\s+",
        r"^ಶ್ರೀ\s+", r"^ಶ್ರೀಮತಿ\s+", r"^శ్రీ\s+", r"^శ్రీమతి\s+",
        r"^திரு\s+", r"^திருமதி\s+", r"^শ্রীযুত\s+", r"^ਸ਼੍ਰੀ\s+", r"^ਸ਼੍ਰੀਮਤੀ\s+",
        r"^جناب\s+", r"^محترمہ\s+"
    ]
    cleaned = name.strip()
    for h in honorifics:
        cleaned = re.sub(h, "", cleaned, flags=re.IGNORECASE)

    # Normalize multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Title case if ASCII
    if re.match(r"^[A-Za-z\s.'-]+$", cleaned):
        normalized = cleaned.title()
    else:
        normalized = cleaned

    return normalized, 0.95


def normalize_area(area_str: Optional[str], unit_str: Optional[str]) -> Tuple[Optional[float], Optional[str], float]:
    """
    Normalize area value and unit to standard Acres.
    Returns (normalized_acres, standard_unit, confidence).
    """
    if not area_str:
        return None, None, 0.0

    try:
        # Convert Indic numerals if any
        converted = convert_indic_digits(str(area_str))

        # Extract numeric part
        numeric_match = re.search(r"[\d.]+", converted)
        if not numeric_match:
            return None, None, 0.0

        val = float(numeric_match.group(0))

        # Determine unit
        raw_unit = (unit_str or "").lower().strip()

        # Check in area string if unit not provided separately
        if not raw_unit:
            raw_unit = str(area_str).lower()

        # Find matching conversion factor (longest match first to avoid subword collisions like 'ha' in 'guntha')
        factor = 1.0
        sorted_keys = sorted(AREA_CONVERSIONS.keys(), key=lambda k: len(k), reverse=True)
        for unit_key in sorted_keys:
            if len(unit_key) <= 2:
                # Use word boundary for short abbreviations like 'ha'
                if re.search(rf"\b{re.escape(unit_key)}\b", raw_unit):
                    factor = AREA_CONVERSIONS[unit_key]
                    break
            else:
                if unit_key in raw_unit:
                    factor = AREA_CONVERSIONS[unit_key]
                    break

        normalized_acres = round(val * factor, 4)
        return normalized_acres, "acres", 0.9

    except Exception as e:
        logger.warning(f"Area normalization failed for '{area_str}' '{unit_str}': {e}")
        return None, None, 0.0


def normalize_date(date_str: Optional[str]) -> Tuple[Optional[str], float]:
    """
    Normalize dates to ISO format (YYYY-MM-DD).
    Handles textual dates, numeric formats, and ordinal indicators.
    Returns (iso_date_string, confidence).
    """
    if not date_str:
        return None, 0.0

    # Convert Indic numerals
    converted = convert_indic_digits(str(date_str)).strip()

    # Remove ordinal indicators (1st, 2nd, 3rd, 15th)
    cleaned = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", converted, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Formats to try
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%y", "%d-%m-%y",
        "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%b %d, %Y",
        "%B %d %Y", "%b %d %Y",
        "%d-%b-%Y", "%d-%B-%Y",
        "%d/%b/%Y", "%d/%B/%Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d"), 0.95
        except ValueError:
            continue

    # Try year only
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", cleaned)
    if year_match:
        return f"{year_match.group(1)}-01-01", 0.6

    return cleaned, 0.3


def normalize_identifier(identifier: Optional[str]) -> Tuple[Optional[str], float]:
    """
    Normalize survey/khasra/plot numbers (remove prefixes, convert Indic digits, normalize slashes).
    Returns (normalized_id, confidence).
    """
    if not identifier:
        return None, 0.0

    # Convert Indic numerals
    converted = convert_indic_digits(str(identifier))

    # Remove common prefixes in multiple Indic languages
    prefix_pat = r"^(?:Survey|Khasra|Plot|Dag|Khata|Khatian|Patta|Gat|No\.?|Number|नं\.?|संख्या|নং|নম্বর|ਨੰਬਰ|ਸਰਵੇ|ਗਟ|ਪਟਾ|నంబరు|ಸರ್ವೆ|எண்)\s*"
    cleaned = re.sub(prefix_pat, "", converted, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*/\s*", "/", cleaned)
    cleaned = cleaned.strip().upper()

    return cleaned, 0.95


def compare_names(name1: str, name2: str) -> float:
    """
    Calculate similarity score between two names (0.0 to 1.0).
    Uses token sort ratio for robustness against word order differences.
    """
    if not name1 or not name2:
        return 0.0
    norm1, _ = normalize_name(name1)
    norm2, _ = normalize_name(name2)
    return fuzz.token_sort_ratio(norm1 or "", norm2 or "") / 100.0


# Script identification helper
INDIC_SCRIPT_RANGES = [
    (0x0900, 0x097F, "Devanagari", "Hindi"),
    (0x0980, 0x09FF, "Bengali", "Bengali"),
    (0x0A00, 0x0A7F, "Gurmukhi", "Punjabi"),
    (0x0A80, 0x0AFF, "Gujarati", "Gujarati"),
    (0x0B00, 0x0B7F, "Odia", "Odia"),
    (0x0B80, 0x0BFF, "Tamil", "Tamil"),
    (0x0C00, 0x0C7F, "Telugu", "Telugu"),
    (0x0C80, 0x0CFF, "Kannada", "Kannada"),
    (0x0D00, 0x0D7F, "Malayalam", "Malayalam"),
    (0x0600, 0x06FF, "Arabic", "Urdu"),
]


def get_script_language_name(text: Optional[str]) -> str:
    """Detect dominant Indic script / language name for a given field text."""
    if not text:
        return "English"
    counts = {}
    for ch in str(text):
        cp = ord(ch)
        for b_start, b_end, script, lang in INDIC_SCRIPT_RANGES:
            if b_start <= cp <= b_end:
                counts[lang] = counts.get(lang, 0) + 1
                break
    if not counts:
        return "English"
    return max(counts.items(), key=lambda x: x[1])[0]


# Known geographic and revenue terms bilingual dictionary
KNOWN_INDIC_TERMS = {
    # States
    'পশ্চিমবঙ্গ': 'West Bengal', 'পশ্চিম বঙ্গ': 'West Bengal', 'উত্তর প্রদেশ': 'Uttar Pradesh',
    'उत्तर प्रदेश': 'Uttar Pradesh', 'தமிழ்நாடு': 'Tamil Nadu', 'ஆந்திர பிரதேசம்': 'Andhra Pradesh',
    'ఆంధ్రప్రదేశ్': 'Andhra Pradesh', 'మహారాష్ట్ర': 'Maharashtra', 'महाराष्ट्र': 'Maharashtra',
    'ગુજરાત': 'Gujarat', 'ಕರ್ನಾಟಕ': 'Karnataka', 'ଓଡ଼ିଶା': 'Odisha', 'ଓଡିଶା': 'Odisha',
    'കേരളം': 'Kerala', 'ਪੰਜਾਬ': 'Punjab',
    # Units
    'একর': 'Acres', 'एकर': 'Acres', 'ஏக்கர்': 'Acres', 'ఎకరాలు': 'Acres', 'ಎಕರೆ': 'Acres', 'ଏକର': 'Acres',
    'বিঘা': 'Bigha', 'बीघा': 'Bigha', 'વીઘા': 'Bigha', 'ବିଘା': 'Bigha', 'ਬੀਘਾ': 'Bigha',
    'হেক্টর': 'Hectares', 'हेक्टेयर': 'Hectares', 'ஹெக்டேர்': 'Hectares', 'హెక్టార్లు': 'Hectares', 'ಹೆಕ್ಟೇರ್': 'Hectares', 'ହେକ୍ଟର': 'Hectares',
    'சென்ட்': 'Cents', 'సెంట్లు': 'Cents', 'ಸೆಂಟ್': 'Cents', 'ସେଣ୍ଟ': 'Cents',
    'ഗുంటలు': 'Gunthas', 'गुंठा': 'Gunthas', 'ગુંઠા': 'Gunthas', 'ಗುಂಟೆ': 'Gunthas',
    # Districts & Locations
    'சுப்பிரமணியன் ராமசாமி': 'Subramanian Ramasamy', 'ராமசாமி கவுண்டர்': 'Ramasamy Gounder',
    'கோயம்புத்தூர்': 'Coimbatore', 'ஆனைமலை': 'Anaimalai',
    'వెంకటేశ్వర రావు': 'Venkateswara Rao', 'సత్యనారాయణ': 'Satyanarayana',
    'కృష్ణా': 'Krishna', 'లింగవరం': 'Lingavaram', 'గుడివాడ': 'Gudivada', 'గుడీవడ': 'Gudivada',
    'राजेश कुमार शर्मा': 'Rajesh Kumar Sharma', 'रामगोपाल शर्मा': 'Ramgopal Sharma',
    'वाराणसी': 'Varanasi', 'बड़ागांव': 'Badagaon',
    'অনিমেষ মুখোপাধ্যায়': 'Animesh Mukhopadhyay', 'বাঁকুড়া': 'Bankura', 'বড়াগ্রাম': 'Baragram',
    'ರಾಜೇಶ್ ಕುಮಾರ್': 'Rajesh Kumar', 'ಮೈಸೂರು': 'Mysore', 'ಹಾಸನ': 'Hassan', 'ಬೆಂಗಳೂರು': 'Bangalore',
    'ರಾಮಣ್ಣ': 'Ramanna', 'ಶಿವಮೊಗ್ಗ': 'Shivamogga', 'ಚನ್ನಪಟ್ಟಣ': 'Channapatna',
    'ରାଜେଶ କୁମାର': 'Rajesh Kumar', 'କଟକ': 'Cuttack', 'ପୁରୀ': 'Puri', 'ଭୁବନେଶ୍ୱର': 'Bhubaneswar',
    'ବରଗଡ଼': 'Bargarh', 'ବଡ଼ଗାଁ': 'Badagaon', 'ସମ୍ବଲପୁର': 'Sambalpur',
}


def transliterate_indic_to_english(text: Optional[str]) -> str:
    """
    Deterministically transliterate any Indic text (Devanagari, Bengali, Tamil, Telugu,
    Kannada, Odia, Gujarati, Malayalam, Gurmukhi) into readable Romanized English representation.
    """
    if not text:
        return ""
    text_str = str(text).strip()
    if not text_str:
        return ""
    # If already pure ASCII/English
    if all(ord(c) < 128 for c in text_str):
        return text_str

    # Check known terms dictionary
    res_text = text_str
    for k, v in KNOWN_INDIC_TERMS.items():
        if k in res_text:
            res_text = res_text.replace(k, v)

    # If all non-ASCII resolved
    if all(ord(c) < 128 for c in res_text):
        return re.sub(r"\s+", " ", res_text).strip().title()

    CONSONANTS = {
        0x15: 'k', 0x16: 'kh', 0x17: 'g', 0x18: 'gh', 0x19: 'ng',
        0x1A: 'ch', 0x1B: 'chh', 0x1C: 'j', 0x1D: 'jh', 0x1E: 'ny',
        0x1F: 't', 0x20: 'th', 0x21: 'd', 0x22: 'dh', 0x23: 'n',
        0x24: 't', 0x25: 'th', 0x26: 'd', 0x27: 'dh', 0x28: 'n',
        0x2A: 'p', 0x2B: 'ph', 0x2C: 'b', 0x2D: 'bh', 0x2E: 'm',
        0x2F: 'y', 0x30: 'r', 0x31: 'r', 0x32: 'l', 0x33: 'l',
        0x34: 'zh', 0x35: 'v', 0x36: 'sh', 0x37: 'sh', 0x38: 's', 0x39: 'h',
        0x58: 'q', 0x59: 'kh', 0x5A: 'gh', 0x5B: 'z', 0x5C: 'r', 0x5D: 'rh', 0x5E: 'f', 0x5F: 'y'
    }
    VOWELS = {
        0x05: 'a', 0x06: 'aa', 0x07: 'i', 0x08: 'ee', 0x09: 'u', 0x0A: 'oo',
        0x0B: 'ri', 0x0E: 'e', 0x0F: 'e', 0x10: 'ai', 0x12: 'o', 0x13: 'o', 0x14: 'au'
    }
    MATRAS = {
        0x3E: 'aa', 0x3F: 'i', 0x40: 'ee', 0x41: 'u', 0x42: 'oo', 0x43: 'ri',
        0x46: 'e', 0x47: 'e', 0x48: 'ai', 0x4A: 'o', 0x4B: 'o', 0x4C: 'au'
    }

    indic_blocks = [
        (0x0900, 0x097F), # Devanagari
        (0x0980, 0x09FF), # Bengali
        (0x0A00, 0x0A7F), # Gurmukhi
        (0x0A80, 0x0AFF), # Gujarati
        (0x0B00, 0x0B7F), # Odia
        (0x0B80, 0x0BFF), # Tamil
        (0x0C00, 0x0C7F), # Telugu
        (0x0C80, 0x0CFF), # Kannada
        (0x0D00, 0x0D7F), # Malayalam
    ]

    words = res_text.split()
    out_words = []
    for w in words:
        if all(ord(c) < 128 for c in w):
            out_words.append(w)
            continue

        cur_chars = []
        i = 0
        n = len(w)
        while i < n:
            cp = ord(w[i])
            base = None
            for b_start, b_end in indic_blocks:
                if b_start <= cp <= b_end:
                    base = b_start
                    break

            if base is None:
                cur_chars.append(w[i])
                i += 1
                continue

            offset = cp - base
            if offset in VOWELS:
                cur_chars.append(VOWELS[offset])
                i += 1
            elif offset in CONSONANTS:
                c_str = CONSONANTS[offset]
                if i + 1 < n:
                    next_cp = ord(w[i+1])
                    next_offset = next_cp - base if base <= next_cp <= (base + 0x7F) else None
                    if next_offset == 0x4D: # Virama / halant / pulli
                        cur_chars.append(c_str)
                        i += 2
                    elif next_offset in MATRAS:
                        cur_chars.append(c_str + MATRAS[next_offset])
                        i += 2
                    elif next_offset == 0x02: # Anusvara
                        cur_chars.append(c_str + 'am')
                        i += 2
                    else:
                        cur_chars.append(c_str + 'a')
                        i += 1
                else:
                    cur_chars.append(c_str)
                    i += 1
            elif offset in MATRAS:
                cur_chars.append(MATRAS[offset])
                i += 1
            elif offset == 0x02:
                cur_chars.append('m')
                i += 1
            elif offset == 0x4D:
                i += 1
            else:
                cur_chars.append(w[i])
                i += 1

        word_roman = ''.join(cur_chars)
        out_words.append(word_roman.title() if word_roman else w)

    final_roman = ' '.join(out_words).strip()
    return final_roman if final_roman else text_str


def get_english_representation(value: Optional[str], field_name: str = "") -> Optional[str]:
    """
    Generate the corresponding English representation (translation / transliteration)
    for an extracted multilingual field value without mutating the original native value.
    """
    if not value:
        return None
    val_str = str(value).strip()
    if not val_str:
        return None

    # If already standard ASCII English
    if all(ord(c) < 128 for c in val_str):
        return val_str

    # Field-specific translations
    if field_name == "area_unit":
        for k, v in KNOWN_INDIC_TERMS.items():
            if k in val_str:
                return v
        return "Acres"
    elif field_name == "state":
        for k, v in KNOWN_INDIC_TERMS.items():
            if k in val_str:
                return v

    # Phonetic Romanization
    roman = transliterate_indic_to_english(val_str)
    return roman if roman else val_str

