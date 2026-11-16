"""Static domain knowledge: categories, document types, recurring processes, acquisition guidance.

Rules for this file:
- Process "suggested documents" are SUGGESTIONS shown with a suggestion label, never presented
  as official requirements.
- Acquisition guidance names official channels. URLs are included only for top-level official
  domains we are confident about; everything else tells the user where to look, not a made-up link.
"""
from __future__ import annotations

CATEGORIES = [
    # key, en, he, icon
    ("identity", "Personal identification", "זיהוי אישי", "id"),
    ("education", "Education", "לימודים", "school"),
    ("military", "Military service", "שירות צבאי", "shield"),
    ("employment", "Employment", "תעסוקה", "briefcase"),
    ("finance", "Finance", "כספים", "bank"),
    ("insurance", "Insurance", "ביטוח", "umbrella"),
    ("medical", "Medical", "רפואי", "heart"),
    ("housing", "Housing", "דיור", "home"),
    ("government", "Government & bureaucracy", "ממשלה וביורוקרטיה", "landmark"),
    ("travel", "Travel", "נסיעות", "plane"),
    ("legal", "Legal", "משפטי", "scale"),
    ("other", "Other", "אחר", "folder"),
]

# Each document type: category, labels, weighted content keywords, filename hints,
# freshness window (days) after which we flag "may be outdated" (a heuristic, shown as such).
DOC_TYPES: dict[str, dict] = {
    "id_card": dict(cat="identity", en="Identity card", he="תעודת זהות", max_age=None,
        kw={"תעודת זהות": 5, "תעודת-זהות": 5, "ת.ז": 3, "ת\"ז": 3, "מספר זהות": 3, "identity card": 5,
            "id card": 4, "מדינת ישראל": 1, "רשות האוכלוסין": 2, "תאריך לידה": 1, "שם האב": 2, "שם האם": 2,
            "מקום לידה": 1, "national id": 3, "teudat zehut": 5, "תעודה ביומטרית": 3},
        fn=["teudat", "zehut", "tz", "id_card", "idcard", "תז", "תעודת_זהות"]),
    "id_appendix": dict(cat="identity", en="ID appendix (sefach)", he="ספח תעודת זהות", max_age=None,
        kw={"ספח": 5, "ספח לתעודת זהות": 6, "appendix": 4, "id appendix": 6, "sefach": 5, "מען": 2,
            "ילדים": 1, "בן/בת זוג": 2, "מצב אישי": 2},
        fn=["sefach", "safach", "ספח", "appendix"]),
    "passport": dict(cat="travel", en="Passport", he="דרכון", max_age=None,
        kw={"דרכון": 5, "passport": 5, "p<isr": 6, "type/סוג": 2, "nationality": 2, "date of expiry": 2},
        fn=["passport", "darkon", "דרכון"]),
    "drivers_license": dict(cat="identity", en="Driver's license", he="רישיון נהיגה", max_age=None,
        kw={"רישיון נהיגה": 6, "רשיון נהיגה": 6, "driving licence": 5, "driver's license": 5,
            "driving license": 5, "משרד התחבורה": 2, "דרגה": 1},
        fn=["license", "licence", "rishayon", "רישיון"]),
    "birth_certificate": dict(cat="identity", en="Birth certificate", he="תעודת לידה", max_age=None,
        kw={"תעודת לידה": 6, "birth certificate": 6, "certificate of birth": 6}, fn=["birth"]),
    "reserve_order": dict(cat="military", en="Reserve duty order", he="צו מילואים", max_age=None,
        kw={"צו מילואים": 6, "צו קריאה": 5, "צו 8": 6, "צו שמונה": 6, "reserve order": 6,
            "call-up order": 5, "call up order": 5, "מתבקש להתייצב": 4, "להתייצב": 2, "ייצוב": 1, "מילואים": 2},
        fn=["tzav", "zav", "צו", "order", "miluim"]),
    "reserve_service_confirmation": dict(cat="military", en="Reserve service confirmation", he="אישור שירות מילואים",
        max_age=365,
        kw={"אישור שירות מילואים": 7, "אישור על שירות מילואים": 7, "ימי מילואים": 4, "ימי שמ\"פ": 4,
            "שירות מילואים פעיל": 5, "reserve service confirmation": 7, "days of reserve service": 5,
            "certificate of reserve service": 6, "טופס 3010": 6, "3010": 2, "מילואים": 2},
        fn=["ishur_miluim", "miluim", "reserve", "מילואים", "3010"]),
    "military_discharge": dict(cat="military", en="Military discharge certificate", he="תעודת שחרור", max_age=None,
        kw={"תעודת שחרור": 7, "תעודת שחרור משירות": 7, "discharge certificate": 7, "שחרור משירות סדיר": 5,
            "certificate of service": 4, "release from service": 4},
        fn=["shichrur", "discharge", "שחרור"]),
    "enrollment_proof": dict(cat="education", en="Proof of enrollment", he="אישור לימודים", max_age=180,
        kw={"אישור לימודים": 7, "אישור על לימודים": 7, "הנו סטודנט": 5, "הינו סטודנט": 5, "היא סטודנטית": 5,
            "לומד/ת": 3, "שנת הלימודים": 3, "proof of enrollment": 7, "enrollment confirmation": 7,
            "certificate of enrollment": 7, "is a registered student": 6, "is enrolled": 5, "academic year": 2,
            "מזכירות אקדמית": 2, "סטודנט מן המניין": 5, "דקאנט": 1},
        fn=["ishur_limudim", "enrollment", "enrolment", "limudim", "אישור_לימודים", "student"]),
    "transcript": dict(cat="education", en="Grade transcript", he="גיליון ציונים", max_age=365,
        kw={"גיליון ציונים": 7, "גליון ציונים": 7, "transcript": 6, "ממוצע": 3, "נקודות זכות": 3, "נ\"ז": 2,
            "grade point": 4, "credits": 2, "ציון סופי": 3},
        fn=["grades", "transcript", "tziunim", "ציונים"]),
    "diploma": dict(cat="education", en="Diploma / degree certificate", he="תעודת תואר / בגרות", max_age=None,
        kw={"תעודת בגרות": 6, "תואר ראשון": 4, "תואר שני": 4, "בוגר": 2, "diploma": 6, "bachelor of": 4,
            "master of": 4, "degree certificate": 6, "has been awarded": 4, "זכאות לתואר": 5},
        fn=["diploma", "degree", "bagrut", "תעודה"]),
    "scholarship_approval": dict(cat="education", en="Scholarship approval", he="אישור מלגה", max_age=None,
        kw={"אישור מלגה": 7, "זכית במלגה": 6, "הוענקה לך מלגה": 6, "scholarship award": 6, "awarded a scholarship": 6,
            "scholarship approval": 7, "מלגה": 2},
        fn=["milga", "scholarship", "מלגה"]),
    "bank_confirmation": dict(cat="finance", en="Bank account confirmation", he="אישור ניהול חשבון", max_age=90,
        kw={"אישור ניהול חשבון": 8, "אישור על ניהול חשבון": 8, "ניהול חשבון": 4, "bank account confirmation": 8,
            "confirmation of bank account": 8, "account ownership": 5, "מספר חשבון": 2, "מספר סניף": 3, "סניף": 1,
            "iban": 2, "בעל החשבון": 3, "בעלי החשבון": 3},
        fn=["ishur_bank", "bank", "nihul", "חשבון"]),
    "bank_statement": dict(cat="finance", en="Bank statement", he="דף חשבון", max_age=90,
        kw={"דף חשבון": 6, "תדפיס חשבון": 6, "bank statement": 6, "יתרה": 2, "תנועות בחשבון": 4, "balance": 1,
            "statement period": 4},
        fn=["statement", "tadpis", "דף_חשבון"]),
    "payslip": dict(cat="employment", en="Payslip", he="תלוש שכר", max_age=90,
        kw={"תלוש שכר": 7, "תלוש משכורת": 7, "payslip": 7, "pay slip": 7, "salary slip": 6, "שכר ברוטו": 4,
            "שכר נטו": 4, "ניכויים": 2, "gross salary": 4, "net salary": 4, "ביטוח לאומי": 1},
        fn=["tlush", "payslip", "salary", "תלוש"]),
    "employment_confirmation": dict(cat="employment", en="Employment confirmation", he="אישור העסקה", max_age=90,
        kw={"אישור העסקה": 7, "אישור על העסקה": 7, "מועסק/ת": 4, "מועסק אצלנו": 5, "employment confirmation": 7,
            "confirmation of employment": 7, "is employed": 5, "employment verification": 6},
        fn=["ishur_haasaka", "employment", "העסקה"]),
    "tax_form_106": dict(cat="finance", en="Form 106 (annual tax)", he="טופס 106", max_age=550,
        kw={"טופס 106": 8, "form 106": 8, "ריכוז נתונים שנתי": 5, "סה\"כ הכנסה": 2, "מס הכנסה": 2},
        fn=["106", "tofes106", "form106"]),
    "insurance_policy": dict(cat="insurance", en="Insurance policy", he="פוליסת ביטוח", max_age=None,
        kw={"פוליסה": 5, "פוליסת ביטוח": 7, "insurance policy": 7, "המבוטח": 3, "the insured": 3, "דמי ביטוח": 3,
            "premium": 2, "תקופת הביטוח": 4},
        fn=["polisa", "policy", "insurance", "ביטוח"]),
    "medical_document": dict(cat="medical", en="Medical document", he="מסמך רפואי", max_age=None,
        kw={"סיכום ביקור": 5, "אבחנה": 4, "הפניה": 3, "מרשם": 3, "diagnosis": 4, "referral": 3, "prescription": 3,
            "קופת חולים": 3, "medical report": 5, "רופא": 2, "physician": 2, "discharge summary": 4, "תוצאות בדיקה": 4},
        fn=["medical", "rofe", "sikum", "רפואי", "referral"]),
    "lease_agreement": dict(cat="housing", en="Rental agreement", he="חוזה שכירות", max_age=None,
        kw={"חוזה שכירות": 8, "הסכם שכירות": 8, "השוכר": 4, "המשכיר": 4, "lease agreement": 8, "rental agreement": 8,
            "tenant": 3, "landlord": 3, "דמי שכירות": 4},
        fn=["lease", "schirut", "שכירות", "rent"]),
    "utility_bill": dict(cat="housing", en="Utility / municipal bill", he="חשבון / ארנונה", max_age=120,
        kw={"ארנונה": 6, "חשבון חשמל": 6, "חשבון מים": 6, "חברת החשמל": 4, "תאגיד מים": 4, "utility bill": 6,
            "electricity bill": 6, "water bill": 6, "property tax": 4, "מונה": 2},
        fn=["arnona", "electric", "hashmal", "bill", "ארנונה"]),
    "contract": dict(cat="legal", en="Contract / agreement", he="חוזה / הסכם", max_age=None,
        kw={"הסכם": 3, "חוזה": 3, "agreement": 3, "contract": 3, "הצדדים": 3, "the parties": 3, "ולראיה באו": 4,
            "in witness whereof": 4},
        fn=["contract", "agreement", "heskem", "חוזה"]),
    "invoice_receipt": dict(cat="finance", en="Invoice / receipt", he="חשבונית / קבלה", max_age=None,
        kw={"חשבונית מס": 6, "קבלה": 3, "invoice": 5, "receipt": 5, "עוסק מורשה": 3, "מע\"מ": 2, "vat": 2,
            "total due": 3},
        fn=["invoice", "receipt", "kabala", "חשבונית"]),
    "government_letter": dict(cat="government", en="Government letter / form", he="מכתב / טופס ממשלתי", max_age=None,
        kw={"ביטוח לאומי": 3, "רשות המסים": 3, "משרד הפנים": 3, "gov.il": 3, "מדינת ישראל": 1, "national insurance": 3,
            "ministry of": 2},
        fn=["bituach", "gov", "misrad"]),
}


def doc_type_label(doc_type: str, lang: str) -> str:
    t = DOC_TYPES.get(doc_type)
    if not t:
        return {"he": "מסמך לא מזוהה", "en": "Unclassified document"}[lang]
    return t[lang]


# Aliases users write in requests (not document contents). Used to map requests to doc types.
REQUEST_ALIASES: dict[str, list[str]] = {
    "id_card": ["תעודת זהות", "תז", "ת.ז", "ת\"ז", "תעודת הזהות", "identity card", "id card", "national id", "my id"],
    "id_appendix": ["ספח", "הספח", "appendix", "sefach", "id appendix"],
    "passport": ["דרכון", "passport"],
    "drivers_license": ["רישיון נהיגה", "רשיון נהיגה", "driver's license", "drivers license", "driving license"],
    "birth_certificate": ["תעודת לידה", "birth certificate"],
    "reserve_order": ["צו מילואים", "צו 8", "צו שמונה", "צו קריאה", "reserve order", "call-up order", "call up order", "military reserve order"],
    "reserve_service_confirmation": ["אישור מילואים", "אישור שירות מילואים", "אישור ימי מילואים", "3010",
                                     "reserve service confirmation", "reserve confirmation", "reserve service certificate"],
    "military_discharge": ["תעודת שחרור", "discharge certificate", "military discharge"],
    "enrollment_proof": ["אישור לימודים", "אישור סטודנט", "proof of enrollment", "enrollment confirmation",
                         "enrolment", "student confirmation", "proof of enrolment"],
    "transcript": ["גיליון ציונים", "גליון ציונים", "ציונים", "transcript", "grades"],
    "diploma": ["תעודת תואר", "תעודת בגרות", "תואר", "diploma", "degree certificate", "bagrut"],
    "scholarship_approval": ["אישור מלגה", "אישור על מלגה", "scholarship approval", "previous scholarship approval"],
    "bank_confirmation": ["אישור ניהול חשבון", "אישור בנק", "אישור חשבון בנק", "bank confirmation",
                          "bank account confirmation", "account confirmation"],
    "bank_statement": ["דף חשבון", "תדפיס", "bank statement"],
    "payslip": ["תלוש שכר", "תלושי שכר", "תלוש", "payslip", "payslips", "pay slip", "salary slip"],
    "employment_confirmation": ["אישור העסקה", "employment confirmation", "proof of employment"],
    "tax_form_106": ["טופס 106", "106", "form 106"],
    "insurance_policy": ["פוליסה", "פוליסת ביטוח", "insurance policy"],
    "medical_document": ["מסמך רפואי", "מסמכים רפואיים", "medical document", "medical records", "הפניה", "referral"],
    "lease_agreement": ["חוזה שכירות", "הסכם שכירות", "lease", "rental agreement"],
    "utility_bill": ["ארנונה", "חשבון חשמל", "חשבון מים", "utility bill", "electricity bill"],
    "contract": ["חוזה", "הסכם", "contract", "agreement"],
    "invoice_receipt": ["חשבונית", "קבלה", "invoice", "receipt"],
}

# Recurring processes. `suggested` = commonly requested documents (SUGGESTIONS ONLY).
PROCESSES: dict[str, dict] = {
    "reserve_scholarship": dict(en="Military reserve scholarship", he="מלגת מילואים",
        triggers=["מלגת מילואים", "מלגה למילואימניקים", "מלגה למשרתי מילואים", "מלגת מילואימניקים",
                  "reserve scholarship", "military reserve scholarship", "reservist scholarship"],
        suggested=["id_card", "id_appendix", "reserve_service_confirmation", "enrollment_proof", "bank_confirmation"]),
    "reserve_benefits": dict(en="Military reserve benefits", he="הטבות מילואים",
        triggers=["הטבות מילואים", "זכויות מילואים", "הטבות למילואימניקים", "מענק מילואים",
                  "reserve benefits", "military reserve benefits", "reservist benefits", "reserve grant"],
        suggested=["id_card", "reserve_service_confirmation", "reserve_order", "bank_confirmation"]),
    "university_registration": dict(en="University registration", he="הרשמה ללימודים",
        triggers=["הרשמה לאוניברסיטה", "רישום לאוניברסיטה", "הרשמה ללימודים", "רישום ללימודים", "הרשמה לתואר",
                  "university registration", "register for university", "university application", "college registration"],
        suggested=["id_card", "id_appendix", "diploma", "military_discharge"]),
    "scholarship": dict(en="Scholarship application", he="בקשת מלגה",
        triggers=["מלגה", "בקשת מלגה", "scholarship", "scholarship application"],
        suggested=["id_card", "enrollment_proof", "bank_confirmation", "transcript"]),
    "apartment_rental": dict(en="Apartment rental", he="שכירת דירה",
        triggers=["שכירת דירה", "לשכור דירה", "השכרת דירה", "rent an apartment", "rental application", "renting an apartment"],
        suggested=["id_card", "payslip", "employment_confirmation", "bank_statement"]),
    "job_onboarding": dict(en="New job onboarding", he="קליטה לעבודה חדשה",
        triggers=["עבודה חדשה", "קליטה לעבודה", "new job", "job onboarding", "job application"],
        suggested=["id_card", "id_appendix", "bank_confirmation", "military_discharge", "diploma"]),
    "tax_refund": dict(en="Tax refund", he="החזר מס",
        triggers=["החזר מס", "tax refund", "tax return"],
        suggested=["tax_form_106", "id_card", "bank_confirmation"]),
    "passport_renewal": dict(en="Passport renewal", he="חידוש דרכון",
        triggers=["חידוש דרכון", "passport renewal", "renew passport", "renew my passport"],
        suggested=["id_card", "passport"]),
}

# Where to obtain a document that was not found anywhere. No invented URLs.
ACQUISITION: dict[str, dict] = {
    "enrollment_proof": dict(
        en=dict(source="Your university / college student portal",
                how="Sign in to the student information portal and look for “Confirmations” → “Proof of enrollment”. Most Israeli institutions issue it instantly as a PDF; otherwise ask the academic secretariat."),
        he=dict(source="פורטל הסטודנט של המוסד האקדמי שלך",
                how="היכנס/י למערכת המידע האישי לסטודנט וחפש/י “אישורים” ← “אישור לימודים”. ברוב המוסדות האישור מופק מיד כ-PDF; אחרת פנה/י למזכירות האקדמית.")),
    "transcript": dict(
        en=dict(source="Your university student portal", how="Look under grades / “Transcript”, or request it from the student secretariat."),
        he=dict(source="פורטל הסטודנט", how="חפש/י תחת ציונים ← “גיליון ציונים”, או בקש/י מהמזכירות.")),
    "diploma": dict(
        en=dict(source="Issuing institution (university graduates office / Ministry of Education for Bagrut)",
                how="Degree certificates are issued by the institution's graduates office. Bagrut certificates are available through the Ministry of Education's official services on gov.il."),
        he=dict(source="המוסד המנפיק (מדור בוגרים / משרד החינוך לתעודת בגרות)",
                how="תעודת תואר מונפקת ע\"י מדור הבוגרים. תעודת בגרות זמינה דרך השירותים הרשמיים של משרד החינוך באתר gov.il."),
        url="https://www.gov.il"),
    "reserve_order": dict(
        en=dict(source="Official IDF reservist channels", how="Reserve orders are available through the IDF's official personal portal for reservists, or from your unit's reserve/personnel officer."),
        he=dict(source="הערוצים הרשמיים של צה\"ל למשרתי מילואים", how="צווי מילואים זמינים באתר האישי הרשמי של צה\"ל למשרתי מילואים, או דרך קצין/ת השלישות ביחידה.")),
    "reserve_service_confirmation": dict(
        en=dict(source="Official IDF reservist channels", how="Confirmation of reserve service days (form 3010) can be downloaded from the IDF's official reservist personal portal, or requested from your unit."),
        he=dict(source="הערוצים הרשמיים של צה\"ל למשרתי מילואים", how="אישור ימי מילואים (טופס 3010) ניתן להפקה באתר האישי הרשמי של צה\"ל למשרתי מילואים, או לבקש מהיחידה.")),
    "military_discharge": dict(
        en=dict(source="Official IDF personal portal", how="A certificate of service / discharge can be requested via the IDF's official personal services."),
        he=dict(source="האתר האישי הרשמי של צה\"ל", how="ניתן להפיק תעודת שחרור / אישור שירות דרך השירותים האישיים הרשמיים של צה\"ל.")),
    "bank_confirmation": dict(
        en=dict(source="Your bank's official app or website", how="Usually under “Confirmations / Documents” → “Account ownership confirmation”. A branch can also issue it."),
        he=dict(source="האפליקציה או האתר הרשמי של הבנק שלך", how="בדרך כלל תחת “אישורים / מסמכים” ← “אישור ניהול חשבון”. ניתן גם לבקש בסניף.")),
    "bank_statement": dict(
        en=dict(source="Your bank's official app or website", how="Export a statement for the required period as PDF."),
        he=dict(source="האפליקציה או האתר הרשמי של הבנק", how="הפק/י תדפיס לתקופה הנדרשת כ-PDF.")),
    "id_card": dict(
        en=dict(source="Population and Immigration Authority", how="If the card is lost, a replacement is issued by appointment at a Population Authority office. Meanwhile, a scan of your existing card may already be on your phone — try uploading photos from your gallery."),
        he=dict(source="רשות האוכלוסין וההגירה", how="אם התעודה אבדה, תעודה חלופית מונפקת בתיאום תור בלשכת רשות האוכלוסין. ייתכן שצילום של התעודה כבר שמור בגלריה — נסה/י להעלות תמונות משם."),
        url="https://www.gov.il"),
    "id_appendix": dict(
        en=dict(source="Population and Immigration Authority", how="An updated ID appendix can be obtained from the Population Authority (some services are available online via gov.il)."),
        he=dict(source="רשות האוכלוסין וההגירה", how="ספח מעודכן ניתן לקבל ברשות האוכלוסין (חלק מהשירותים זמינים מקוון דרך gov.il)."),
        url="https://www.gov.il"),
    "passport": dict(
        en=dict(source="Population and Immigration Authority", how="Passport issue/renewal is handled by the Population Authority, partly online via gov.il."),
        he=dict(source="רשות האוכלוסין וההגירה", how="הנפקה/חידוש דרכון מטופלים ברשות האוכלוסין, חלקית באופן מקוון דרך gov.il."),
        url="https://www.gov.il"),
    "payslip": dict(
        en=dict(source="Your employer / payroll portal", how="Ask HR or download from your employer's payroll system."),
        he=dict(source="המעסיק / מערכת השכר", how="פנה/י למשאבי אנוש או הורד/י ממערכת השכר של המעסיק.")),
    "employment_confirmation": dict(
        en=dict(source="Your employer's HR department", how="Request a signed employment confirmation letter."),
        he=dict(source="מחלקת משאבי אנוש אצל המעסיק", how="בקש/י אישור העסקה חתום.")),
    "tax_form_106": dict(
        en=dict(source="Your employer", how="Employers issue Form 106 annually (usually by end of March). Ask HR/payroll for the relevant tax year."),
        he=dict(source="המעסיק", how="המעסיק מנפיק טופס 106 פעם בשנה (בד\"כ עד סוף מרץ). בקש/י ממשאבי אנוש/שכר לשנת המס הרלוונטית.")),
    "utility_bill": dict(
        en=dict(source="The utility provider / municipality website", how="Download the latest bill from the provider's or municipality's official site."),
        he=dict(source="אתר ספק השירות / הרשות המקומית", how="הורד/י את החשבון האחרון מהאתר הרשמי של הספק או העירייה.")),
    "insurance_policy": dict(
        en=dict(source="Your insurance company's personal area", how="Policies are available in the insurer's official personal area or from your agent."),
        he=dict(source="האזור האישי בחברת הביטוח", how="הפוליסה זמינה באזור האישי באתר חברת הביטוח או אצל הסוכן.")),
    "medical_document": dict(
        en=dict(source="Your health fund (kupat holim) personal area", how="Visit summaries, referrals and results are usually available in your health fund's app or website."),
        he=dict(source="האזור האישי בקופת החולים", how="סיכומי ביקור, הפניות ותוצאות זמינים בדרך כלל באפליקציה או באתר של קופת החולים.")),
    "scholarship_approval": dict(
        en=dict(source="The scholarship provider", how="Check the provider's portal or the approval email you received."),
        he=dict(source="הגוף המעניק את המלגה", how="בדוק/י בפורטל של הגוף המעניק או במייל האישור שקיבלת.")),
}


def acquisition_for(doc_type: str, lang: str) -> dict | None:
    a = ACQUISITION.get(doc_type)
    if not a:
        return None
    out = dict(a[lang])
    if a.get("url"):
        out["url"] = a["url"]
    return out


KNOWN_ISSUERS = [
    # (pattern, canonical name)
    ("בנק הפועלים", "Bank Hapoalim"), ("bank hapoalim", "Bank Hapoalim"),
    ("בנק לאומי", "Bank Leumi"), ("bank leumi", "Bank Leumi"),
    ("בנק דיסקונט", "Discount Bank"), ("discount bank", "Discount Bank"),
    ("מזרחי טפחות", "Mizrahi Tefahot"), ("mizrahi", "Mizrahi Tefahot"),
    ("הבנק הבינלאומי", "First International Bank"), ("בנק ירושלים", "Bank of Jerusalem"),
    ("בנק מרכנתיל", "Mercantile Bank"), ("one zero", "One Zero"), ("וואן זירו", "One Zero"),
    ("צבא הגנה לישראל", "IDF"), ("צה\"ל", "IDF"), ("israel defense forces", "IDF"), ("idf", "IDF"),
    ("רשות האוכלוסין", "Population and Immigration Authority"),
    ("population and immigration", "Population and Immigration Authority"),
    ("משרד הפנים", "Ministry of Interior"), ("ministry of interior", "Ministry of Interior"),
    ("ביטוח לאומי", "National Insurance Institute"), ("national insurance", "National Insurance Institute"),
    ("רשות המסים", "Israel Tax Authority"), ("tax authority", "Israel Tax Authority"),
    ("האוניברסיטה העברית", "Hebrew University"), ("hebrew university", "Hebrew University"),
    ("אוניברסיטת תל אביב", "Tel Aviv University"), ("tel aviv university", "Tel Aviv University"),
    ("הטכניון", "Technion"), ("technion", "Technion"),
    ("אוניברסיטת בן גוריון", "Ben-Gurion University"), ("ben-gurion university", "Ben-Gurion University"),
    ("אוניברסיטת בר אילן", "Bar-Ilan University"), ("אוניברסיטת בר-אילן", "Bar-Ilan University"), ("bar-ilan", "Bar-Ilan University"),
    ("אוניברסיטת חיפה", "University of Haifa"), ("university of haifa", "University of Haifa"),
    ("האוניברסיטה הפתוחה", "Open University"), ("open university", "Open University"),
    ("רייכמן", "Reichman University"), ("reichman", "Reichman University"),
    ("מכון ויצמן", "Weizmann Institute"),
    ("שירותי בריאות כללית", "Clalit"), ("כללית", "Clalit"), ("מכבי שירותי בריאות", "Maccabi"), ("קופת חולים מאוחדת", "Meuhedet"), ("לאומית שירותי בריאות", "Leumit"),
    ("משרד התחבורה", "Ministry of Transport"), ("חברת החשמל", "Israel Electric Corporation"),
]
