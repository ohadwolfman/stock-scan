<div dir="rtl">

# סורק 12 השלבים של Tom Nash

כלי שורת פקודה שבודק כל טיקר מול תהליך המחקר בן 12 השלבים מתוך "How to Find the Best Stocks in the Market". לכל טיקר הוא עונה על שתי שאלות:

1. האם החברה שורדת את כל 12 השלבים? אם לא, באיזה שלב היא הודחה ולמה.
2. כמה היא קרובה? כל בדיקה עם הערך, הסף, המרחק מהמעבר ומקור הנתון, וכרטיס ניקוד של 13 קטגוריות.

הנתונים מגיעים מ yfinance בלבד, טריים בכל ריצה (עם מטמון יומי). ערך חסר הופך את הבדיקה ל"חסר" (UNKNOWN), אף פעם לא ל"עבר".

## התקנה

```powershell
cd nash_screener
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## הרצה

```powershell
python nash_screen.py NVDA MSFT APLD IONQ
python nash_screen.py --file tickers.txt          # טיקר בכל שורה, או מופרדים בפסיקים או רווחים
python nash_screen.py NVDA --refresh              # התעלמות מהמטמון של היום
python nash_screen.py NVDA MSFT --init-manual     # יצירה או הרחבה של nash_manual.yaml
```

אפשרויות נוספות: `--manual PATH`, `--cache-dir`, `--reports-dir`.

## תהליך העבודה המומלץ

1. מריצים על רשימה ארוכה בלי שום קלט ידני. רוב השמות מודחים על סמך המספרים בשלבים 2 ו 3 (<span dir="ltr">"most companies die right here"</span>).
2. לשמות שיצאו `INCOMPLETE` בלבד מריצים `--init-manual`. הקובץ נוצר עם רמזים מ yfinance בתור הערות YAML: תיאור העסק, מדינה, סקטור, נושאי משרה, תאריך מסחר ראשון, רכישות בעלי עניין, עקיפות רווח, רכישות מול FCF ועוד.
3. ממלאים את השדות ש"מה חסר" בדוח מציין, ומריצים שוב. `--init-manual` לעולם לא דורס ערך שכבר מולא.

ממלאים רק את מה שצריך: בדיקה שכבר נכשלה על המספרים לא מחכה לשיפוט ידני, ושדות ידניים שלא משנים את התוצאה (למשל `step2_valid_reason` כששלוש השאלות עברו) לא נדרשים.

## פלטים (בתיקייה reports)

| קובץ | תוכן |
|---|---|
| <span dir="ltr">`nash_report_YYYY-MM-DD_HHMM.html`</span> | דוח מלא בעברית: חמשת הכללים, פסק דין, 12 השלבים, כרטיס ניקוד, הערכת שווי, מה חסר, הנחות ומקורות |
| <span dir="ltr">`nash_summary_YYYY-MM-DD_HHMM.csv`</span> | שורה לכל טיקר, סטטוס וערך של כל בדיקה, למיון וסינון |
| <span dir="ltr">`nash_raw_YYYY-MM-DD_HHMM.json`</span> | כל הנתונים הגולמיים, התוויות ששימשו, המרות מטבע וזמנים |

בקונסולה: שורה לכל טיקר עם פסק הדין, שלב ההדחה, ניקוד (מחושב + ידני וטווח אפשרי), מחיר, שווי שוק, אחוז שלמות נתונים וזמן ציטוט.

## פסק הדין

* <span dir="ltr">`ELIMINATED AT STEP N`</span>: השלב הראשון לפי הסדר שנכשל. כל 12 השלבים מחושבים תמיד, כך שרואים את התמונה המלאה.
* <span dir="ltr">`INCOMPLETE`</span>: אף שלב לא נכשל, אבל חסרים נתונים. הדוח מפרט בדיוק אילו שדות.
* <span dir="ltr">`SURVIVED ALL 12`</span>: <span dir="ltr">"A company you could own for 20 years."</span>

## מבנה

| קובץ | תפקיד |
|---|---|
| `config.py` | כל ספי המסמך לפי שלב, וההנחות A1 עד A25 |
| `fetch.py` | גישה ל yfinance, מטמון יומי, ניסיונות חוזרים, שערי מטבע |
| `metrics.py` | חישובים נגזרים (TTM, צמיחה, מרווחים) עם מקור לכל ערך |
| `steps.py` | שלבים 1 עד 12 ולוגיקת פסק הדין |
| `scorecard.py` | 13 הקטגוריות, מינימום ומקסימום כשחסרים ציונים ידניים |
| `valuation.py` | DCF, DCF הפוך, מכפילים, PEG |
| `manual.py` | קובץ YAML ידני, אימות, `--init-manual` |
| `report.py` | HTML, CSV, JSON וקונסולה |

הנחות שהמסמך לא מגדיר (A1 עד A19 מהאפיון, A20 עד A25 נוספו במימוש) מופיעות ב `config.py` ומודפסות בדוח בכל פעם שהן מופעלות.

## בדיקות

```powershell
python -m pytest -q
```

הבדיקות רצות על נתונים סינתטיים בלבד (`tests/fixtures.py`) ולא צריכות רשת.

חינוך, לא ייעוץ פיננסי.

</div>
