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
3. להפעיל:
   - Windows: לחיצה כפולה על `start.bat`
   - Mac: לפתוח טרמינל בתיקייה `docmind` ולהריץ `./start.sh`
4. לפתוח בדפדפן את http://localhost:8000
5. (רשות) לתמונות iPhone בפורמט HEIC: להתקין ImageMagick (חינם, imagemagick.org)

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

## כספת — תיקיות מוגנות בקוד
הגדרות ← "הגדרת קוד כספת" (סיסמת החשבון + קוד של 4 עד 12 ספרות). מיד אחר כך התיקיות זיהוי אישי, כספים ורפואי מוגנות. את התיקיות המוגנות משנים במסך קטגוריות, בכפתור "מוגנת" על כל תיקייה.
כשהכספת נעולה, המסמכים האלה מוסתרים לגמרי: שם, תוכן, תצוגה, הורדה וחיפוש. לחיצה על "מסמך מוגן" מבקשת את הקוד. הכספת ננעלת לבד אחרי 5 דקות או כשיוצאים מהאפליקציה. אחרי 5 קודים שגויים היא ננעלת ל-15 דקות.

## אימות דו-שלבי (מומלץ, בחינם)
הגדרות ← אימות דו-שלבי ← הפעלה. מוסיפים את DocMind לאפליקציית Google Authenticator, מקלידים את הקוד, ושומרים את 8 קודי הגיבוי במקום בטוח.

## תזכורות תוקף (בחינם)
מסמך עם תאריך תוקף מופיע בדף הבית לפני שהוא פג. כפתור "הוספה ליומן" מוריד קובץ יומן שנפתח ב-Google Calendar, ביומן של iPhone וב-Outlook. בהגדרות בוחרים כמה זמן מראש להזכיר: 14, 30, 60 או 90 ימים.

## בדיקה
לשאול את העוזר: "תמצא את טופס 106" או "תמצא את אישור הלימודים". מה שנמצא במייל יסומן "נמצא בחוץ — עדיין לא הורד", עם כפתור "פתיחת המייל" וכפתור "הורדה לספרייה".
