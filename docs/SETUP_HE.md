# הפעלת DocMind וחיבור Gmail ו-Google Drive — בחינם

## עלויות — בדיקה (נובמבר 2026)
| רכיב | עלות |
|---|---|
| Python, Tesseract (OCR כולל עברית), poppler, כל הספריות | חינם, קוד פתוח |
| הרצה על המחשב שלך | חינם |
| פרויקט ב-Google Cloud + Gmail API + Drive API | חינם לשימוש רגיל (אין צורך בכרטיס אשראי) |
| מצב "Testing" ב-Google (עד 100 משתמשים) | חינם |
| ספק AI חיצוני | לא בשימוש (כבוי כברירת מחדל) |
| **השקה ציבורית מעבר ל-100 משתמשים** | **בתשלום**: בדיקת אבטחה CASA, כ-540 עד 1,000 דולר בשנה |

הערה: במצב Testing גוגל מנתקת את החיבור כל 7 ימים. DocMind יציג "נדרש חיבור מחדש", ולוחצים "חיבור" שוב.

## שלב 1 — הרצה על המחשב (פעם אחת)
1. להתקין Python 3.11 ומעלה (python.org).
2. להתקין Tesseract עם עברית:
   - Windows: להתקין מ-UB-Mannheim/tesseract, ובהתקנה לסמן את השפה Hebrew. בנוסף להתקין את poppler ל-Windows ולהוסיף אותו ל-PATH.
   - Mac: `brew install tesseract tesseract-lang poppler`
3. לפתוח טרמינל בתיקייה `docmind/backend` ולהריץ:
   ```
   pip install -r requirements.txt
   python run.py
   ```
4. לפתוח בדפדפן את http://localhost:8000

## שלב 2 — יצירת פרטי חיבור ל-Google (כ-10 דקות)
1. להיכנס ל-console.cloud.google.com ← **New Project** ← לתת שם (למשל DocMind) ← Create.
2. **APIs & Services ← Library**: לחפש ולהפעיל (Enable) את **Gmail API** ואת **Google Drive API**.
3. **Google Auth Platform / OAuth consent screen**:
   - User type: **External**
   - App name: DocMind, ולמלא אימייל תמיכה
   - Audience / Test users: להוסיף את כתובת ה-Gmail שלך
   - להשאיר במצב **Testing** (לא לפרסם)
4. **Clients ← Create client** ← סוג: **Web application**
   - Authorized redirect URI: `http://localhost:8000/api/oauth/google/callback`
   - Create ← להעתיק את **Client ID** ואת **Client secret**
5. בתיקייה `docmind`: להעתיק את `.env.example` לקובץ בשם `.env` ולמלא:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/oauth/google/callback
   ```
   חשוב: לא לשלוח את ה-secret לאף אחד, גם לא בצ'אט.
6. לעצור את השרת (Ctrl+C) ולהריץ שוב `python run.py`. הקובץ `.env` נטען אוטומטית.
7. באפליקציה: **עוד ← מקורות מחוברים ← Gmail ← חיבור**. גוגל תציג אזהרה "האפליקציה לא אומתה", וזה תקין כשהאפליקציה שלך: Advanced ← Go to DocMind ← לאשר.
8. לחזור על אותו הדבר עבור Google Drive.

## בדיקה
לשאול את העוזר: "תמצא את טופס 106" או "תמצא את אישור הלימודים". מה שנמצא במייל יסומן "נמצא בחוץ — עדיין לא הורד", עם כפתור "פתיחת המייל" וכפתור "הורדה לספרייה".
