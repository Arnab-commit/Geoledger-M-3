"""
Test script for verifying multilingual (English, Hindi, Bengali) extraction.
"""
from test_ocr_prototype import extract_all_revenue_fields

def test_multilingual():
    hindi_text = """
    उत्तर प्रदेश सरकार - राजस्व परिषद
    दाखिल खारिज / नामांतरण प्रमाण पत्र
    नामांतरण सं: MUT/UP/2023/8891
    नामांतरण दिनांक: 14/08/2023
    जिला: वाराणसी
    तहसील: पिंडरा
    ग्राम: शिवपुर
    मौजा: शिवपुर
    खाता संख्या: 742
    खसरा नं: 389/1
    रकबा: 1.25 हेक्टेयर
    खातेदार का नाम: रामेश्वर प्रसाद
    पिता का नाम: दीनदयाल प्रसाद
    पूर्व मालिक: श्यामाचरण
    क्रेता: रामेश्वर प्रसाद
    पंजीकरण सं: REG/VAR/2023/1029
    """

    bengali_text = """
    পশ্চিমবঙ্গ সরকার - ভূমি ও ভূমি রাজস্ব দপ্তর
    খতিয়ান ও রেকর্ড অব রাইটস (ROR)
    মিউটেশন কেস নং: MUT/WB/2021/7710
    তারিখ: 10/11/2021
    জেলা: বাঁকুড়া
    ব্লক: রানিবাঁধ
    মৌজা: অম্বিকানগর
    খতিয়ান নং: ৫১২
    দাগ নং: ৮৯০
    জমির পরিমাণ: ২.৫০ একর
    মালিকের নাম: সুবোধ রায়
    পিতার নাম: রামপদ রায়
    পূর্ব মালিক: গোপাল সেন
    নতুন মালিক: সুবোধ রায়
    দলিল নং: DEED/2021/4491
    """

    print("=== Testing Hindi Extraction ===")
    h_res = extract_all_revenue_fields(hindi_text)
    for k, v in sorted(h_res.items()):
        print(f"  {k:22}: {v}")

    print("\n=== Testing Bengali Extraction ===")
    b_res = extract_all_revenue_fields(bengali_text)
    for k, v in sorted(b_res.items()):
        print(f"  {k:22}: {v}")

if __name__ == "__main__":
    test_multilingual()
