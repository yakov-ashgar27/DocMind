"""Assistant phrasing in Hebrew and English."""
from __future__ import annotations

T = {
    "greeting": {
        "en": "Hi {name}! Tell me what you need — for example “I need documents for a reserve scholarship” or “find my bank confirmation”.",
        "he": "היי {name}! ספר/י לי מה צריך — למשל “אני צריך מסמכים למלגת מילואים” או “תמצא לי את אישור ניהול החשבון”.",
    },
    "help": {
        "en": "I find your documents across every source you've connected, remember the documents you need for recurring tasks (only after you approve), and prepare a bundle you can download file by file. Try: “Prepare everything for my university registration”.",
        "he": "אני מוצא מסמכים בכל המקורות שחיברת, זוכר אילו מסמכים נדרשים למשימות חוזרות (רק באישורך), ומכין תיק מסמכים להורדה קובץ-קובץ. נסה/י: “תכין לי את כל מה שצריך להרשמה ללימודים”.",
    },
    "ask_checklist": {
        "en": "Got it — {task}. Which documents were required? List them and I'll search for each one.",
        "he": "הבנתי — {task}. אילו מסמכים נדרשים? פרט/י ואחפש כל אחד מהם.",
    },
    "suggestions_note": {
        "en": "Commonly requested for this kind of task — suggestions only, not confirmed requirements:",
        "he": "מסמכים שנדרשים לרוב במשימה כזו — הצעות בלבד, לא דרישות מאושרות:",
    },
    "use_suggestions": {"en": "Use these", "he": "להשתמש בהצעות"},
    "ask_checklist_again": {
        "en": "I couldn't identify document names in that. You can tap the suggestions or write e.g. “identity card, proof of enrollment, bank confirmation”.",
        "he": "לא זיהיתי שמות מסמכים. אפשר ללחוץ על ההצעות או לכתוב למשל “תעודת זהות, אישור לימודים, אישור ניהול חשבון”.",
    },
    "remembered": {
        "en": "You've done this before. I used your saved checklist “{name}” ({n} documents) and searched for each one.",
        "he": "עשית את זה בעבר. השתמשתי ברשימה השמורה “{name}” ({n} מסמכים) וחיפשתי כל אחד מהם.",
    },
    "searched_summary": {
        "en": "Found {found} of {total}. Sources searched: {sources}.",
        "he": "נמצאו {found} מתוך {total}. מקורות שנבדקו: {sources}.",
    },
    "not_searched": {
        "en": "Not searched (not connected): {sources}.",
        "he": "לא נבדקו (לא מחוברים): {sources}.",
    },
    "search_failed": {
        "en": "Couldn't complete the search in: {sources}. Items not found there are marked “search incomplete”, not missing.",
        "he": "החיפוש לא הושלם ב: {sources}. מסמכים שלא נמצאו מסומנים “חיפוש לא הושלם” ולא “חסר”.",
    },
    "outdated_note": {
        "en": "{n} document(s) may be outdated — please check the dates before submitting.",
        "he": "{n} מסמכים עשויים להיות לא עדכניים — כדאי לבדוק את התאריכים לפני ההגשה.",
    },
    "anything_changed": {
        "en": "Has anything changed in the requirements this time? Are there any additional documents required?",
        "he": "השתנה משהו בדרישות הפעם? יש מסמכים נוספים שנדרשים?",
    },
    "additional": {
        "en": "Are there any additional documents required?",
        "he": "יש מסמכים נוספים שנדרשים?",
    },
    "propose_save": {
        "en": "Should I remember this checklist for future “{task}” applications?",
        "he": "לזכור את רשימת המסמכים הזו לפעמים הבאות של “{task}”?",
    },
    "propose_update": {
        "en": "Your saved checklist “{name}” doesn't include {added}. Update the saved checklist?",
        "he": "ברשימה השמורה “{name}” לא מופיע {added}. לעדכן את הרשימה השמורה?",
    },
    "saved": {
        "en": "Saved. Next time you mention “{task}”, I'll start from this checklist and ask whether anything changed.",
        "he": "נשמר. בפעם הבאה שתזכיר/י “{task}”, אתחיל מהרשימה הזו ואשאל אם משהו השתנה.",
    },
    "updated": {"en": "Updated your saved checklist.", "he": "הרשימה השמורה עודכנה."},
    "not_saved": {"en": "OK, I won't save it.", "he": "בסדר, לא אשמור."},
    "added_items": {"en": "Added and searched: {items}.", "he": "הוספתי וחיפשתי: {items}."},
    "complete": {
        "en": "Great. Want me to put these into a bundle so you can preview and download each file?",
        "he": "מעולה. להכין מהם תיק מסמכים שאפשר לצפות בו ולהוריד כל קובץ בנפרד?",
    },
    "find_summary": {"en": "Here's what I found. Sources searched: {sources}.", "he": "זה מה שמצאתי. מקורות שנבדקו: {sources}."},
    "anything_else": {"en": "Need anything else?", "he": "צריך עוד משהו?"},
    "free_results": {
        "en": "I couldn't map that to a specific document type, so I searched the contents of your documents. Closest matches:",
        "he": "לא זיהיתי סוג מסמך מסוים, אז חיפשתי בתוכן המסמכים שלך. ההתאמות הקרובות ביותר:",
    },
    "free_none": {
        "en": "I didn't find anything matching that in your documents. Try naming the document (e.g. “payslip”, “passport”), or upload it first.",
        "he": "לא מצאתי משהו מתאים במסמכים שלך. נסה/י לציין את שם המסמך (למשל “תלוש שכר”, “דרכון”), או להעלות אותו קודם.",
    },
    "empty_library": {
        "en": "Your library is empty, so there's nothing to search yet. Upload documents (or import a WhatsApp chat export) and I'll classify them automatically.",
        "he": "הספרייה עדיין ריקה, אז אין במה לחפש. העלה/י מסמכים (או ייבא/י צ'אט מוואטסאפ) ואסווג אותם אוטומטית.",
    },
    "create_bundle": {"en": "Create bundle", "he": "יצירת תיק מסמכים"},
    "remember_yes": {"en": "Remember it", "he": "כן, לזכור"},
    "remember_no": {"en": "Not now", "he": "לא עכשיו"},
    "update_yes": {"en": "Update checklist", "he": "לעדכן רשימה"},
    "update_no": {"en": "Keep as is", "he": "להשאיר כמו שהוא"},
    "nothing_more": {"en": "That's all", "he": "זה הכל"},
}


def t(key: str, lang: str, **kw) -> str:
    return T[key][lang].format(**kw)


def join_list(items: list[str], lang: str) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return (", ".join(items[:-1]) + (" ו" if lang == "he" else " and ") + items[-1])
