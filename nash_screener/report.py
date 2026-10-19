"""Outputs: console table, self-contained Hebrew RTL HTML report, CSV summary, raw JSON."""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
from pathlib import Path

import config
from steps import FAIL, INFO, PASS, UNKNOWN, fmt, money

STATUS_HE = {PASS: "עבר", FAIL: "נכשל", UNKNOWN: "חסר", INFO: "מידע"}


def verdict_he(r) -> str:
    if r.verdict.startswith("ELIMINATED"):
        return f"הודחה בשלב {r.eliminated_at}"
    if r.verdict == "INCOMPLETE":
        return "לא הושלם: חסרים נתונים"
    if r.verdict == "SURVIVED ALL 12":
        return "שרדה את כל 12 השלבים"
    return r.verdict


def score_text(sc) -> str:
    s = f"{sc['computed']}+{sc['manual']}={sc['min']}"
    return s if sc["complete"] else f"{s} [{sc['min']}-{sc['max']}]"


# ------------------------------------------------------------------ console
def console_table(results, errors: dict) -> str:
    head = ["Ticker", "Verdict", "Elim", "Score /130 (comp+man) [range]", "Price", "Mkt cap", "Data %", "Quote time"]
    rows = []
    for r in results:
        h = r.header
        rows.append([r.ticker, r.verdict, str(r.eliminated_at or "-"), score_text(r.score),
                     f"{fmt(h['price'], '', 2)} {h.get('currency') or ''}".strip(), money(h["market_cap"]),
                     f"{r.completeness:.0f}%", str(h.get("quote_time") or "n/a")])
    for t, e in errors.items():
        rows.append([t, "ERROR", "-", "-", "-", "-", "0%", e[:40]])
    widths = [max(len(str(x)) for x in col) for col in zip(head, *rows)] if rows else [len(h) for h in head]
    line = lambda cells: "  ".join(str(c).ljust(w) for c, w in zip(cells, widths))
    out = [line(head), line(["-" * w for w in widths])] + [line(r) for r in rows]
    return "\n".join(out)


# ------------------------------------------------------------------ HTML
CSS = """
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--pass:#1f7a3a;--pass-bg:#e5f4ea;
--fail:#b42318;--fail-bg:#fdecea;--unk:#8a5a00;--unk-bg:#fff4dc;--info:#3b5b8c;--info-bg:#eaf0f8;--accent:#2f4f8f}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141416;--card:#1d1d20;--fg:#ececee;
--muted:#a0a0a8;--line:#323238;--pass:#7fd49a;--pass-bg:#183323;--fail:#ff8a80;--fail-bg:#3a1a18;--unk:#f2c46d;
--unk-bg:#3a2e14;--info:#9db8e6;--info-bg:#1c2738;--accent:#9db8e6}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 "Segoe UI",Arial,"Noto Sans Hebrew",sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:20px;margin:0}h3{font-size:16px;margin:18px 0 8px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin:16px 0}
.ltr{direction:ltr;unicode-bidi:isolate;text-align:left}
.en{direction:ltr;unicode-bidi:isolate;font-style:italic;color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);
padding:6px 8px;vertical-align:top;text-align:right}th{color:var(--muted);font-weight:600;white-space:nowrap}
td.ltr{text-align:left}
.tbl{overflow-x:auto}
.b{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:600;white-space:nowrap}
.PASS{background:var(--pass-bg);color:var(--pass)}.FAIL{background:var(--fail-bg);color:var(--fail)}
.UNKNOWN{background:var(--unk-bg);color:var(--unk)}.INFO{background:var(--info-bg);color:var(--info)}
.verdict{border-radius:10px;padding:14px 16px;margin:12px 0;border:1px solid var(--line)}
.verdict.FAIL{border-color:var(--fail)}.verdict.PASS{border-color:var(--pass)}.verdict.UNKNOWN{border-color:var(--unk)}
.verdict .big{font-size:20px;font-weight:700}
details{border:1px solid var(--line);border-radius:8px;margin:8px 0;background:var(--card)}
summary{cursor:pointer;padding:10px 12px;font-weight:600;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
details>div{padding:0 12px 12px}
.kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px 16px;margin:8px 0}
.kv div span{display:block;color:var(--muted);font-size:12px}
.kv b.ltr{display:block;text-align:right;overflow-wrap:anywhere}
code{background:var(--info-bg);border-radius:4px;padding:0 4px;direction:ltr;unicode-bidi:isolate}
ol.rules li{margin:2px 0}footer{margin-top:32px;text-align:center;color:var(--muted)}
.req{color:var(--muted);font-size:11px}
"""


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def badge(status) -> str:
    return f'<span class="b {status}">{STATUS_HE.get(status, status)}</span>'


def verdict_class(r):
    return FAIL if r.eliminated_at else (UNKNOWN if r.verdict == "INCOMPLETE" else PASS)


def html_report(results, run_meta: dict, errors: dict) -> str:
    parts = [f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Nash 12-Step Report</title>
<style>{CSS}</style></head><body><main>
<h1>דוח סינון לפי 12 השלבים של Tom Nash</h1>
<div class="muted"><span class="ltr">How to Find the Best Stocks in the Market</span> · הופק
<span class="ltr">{e(run_meta['generated'])}</span> · <span class="ltr">yfinance {e(run_meta.get('yfinance'))}</span></div>
<div class="card"><h3>חמשת הכללים</h3><ol class="rules">"""]
    for num, title, text in config.FIVE_RULES:
        parts.append(f'<li><span class="ltr"><b>{e(title)}</b>: {e(text)}</span></li>')
    parts.append("</ol></div>")

    # summary table
    parts.append('<div class="card"><h3>סיכום</h3><div class="tbl"><table><tr><th>טיקר</th><th>פסק דין</th>'
                 '<th>ניקוד /130</th><th>מחיר</th><th>שווי שוק</th><th>שלמות נתונים</th><th>זמן ציטוט</th></tr>')
    for r in results:
        h = r.header
        parts.append(f'<tr><td class="ltr"><a href="#t-{e(r.ticker)}">{e(r.ticker)}</a></td>'
                     f'<td>{badge(verdict_class(r))} {e(verdict_he(r))}</td>'
                     f'<td class="ltr">{e(score_text(r.score))}</td>'
                     f'<td class="ltr">{e(fmt(h["price"], "", 2))} {e(h.get("currency"))}</td>'
                     f'<td class="ltr">{e(money(h["market_cap"]))}</td><td class="ltr">{r.completeness:.0f}%</td>'
                     f'<td class="ltr">{e(h.get("quote_time"))}</td></tr>')
    for t, err in errors.items():
        parts.append(f'<tr><td class="ltr">{e(t)}</td><td>{badge(UNKNOWN)} שגיאה</td>'
                     f'<td class="ltr" colspan="5">{e(err)}</td></tr>')
    parts.append("</table></div></div>")

    for r in results:
        parts.append(ticker_section(r))

    parts.append('<div class="card"><h3>חוסר עקביות ידוע במסמך</h3><ol>')
    for k in config.KNOWN_INCONSISTENCIES:
        parts.append(f'<li class="ltr">{e(k)}</li>')
    parts.append("</ol></div>")
    parts.append(f"<footer>{e(config.DISCLAIMER_HE)}</footer></main></body></html>")
    return "\n".join(parts)


def checks_table(step) -> str:
    rows = ['<div class="tbl"><table><tr><th>סטטוס</th><th>בדיקה</th><th>ערך</th><th>סף</th><th>מרחק</th>'
            '<th>מקור</th><th>הערה</th></tr>']
    for c in step.checks:
        quote = f'<div class="en">"{e(c.quote)}"</div>' if c.quote else ""
        req = "" if c.required or c.status == INFO else '<div class="req">לא חובה</div>'
        asm = f' <span class="muted">({", ".join(c.assumptions)})</span>' if c.assumptions else ""
        rows.append(f"<tr><td>{badge(c.status)}{req}</td><td>{e(c.name)}{quote}</td>"
                    f'<td class="ltr">{e(c.value)}</td><td class="ltr">{e(c.threshold)}</td>'
                    f'<td class="ltr">{e(c.distance)}</td><td class="ltr">{e(c.source)}</td>'
                    f'<td class="ltr">{e(c.note)}{asm}</td></tr>')
    rows.append("</table></div>")
    return "".join(rows)


def ticker_section(r) -> str:
    h = r.header
    vc = verdict_class(r)
    p = [f'<section class="card" id="t-{e(r.ticker)}"><h2><span class="ltr">{e(r.ticker)}</span> · '
         f'<span class="ltr">{e(h["name"])}</span></h2>']
    p.append(f'<div class="kv">'
             f'<div><span>מחיר</span><b class="ltr">{e(fmt(h["price"], "", 2))} {e(h.get("currency"))}</b>'
             f' <span class="ltr">{e(h["price_source"])}</span></div>'
             f'<div><span>שווי שוק</span><b class="ltr">{e(money(h["market_cap"]))}</b>'
             f' <span class="ltr">USD {e(money(h["market_cap_usd"]))}</span></div>'
             f'<div><span>זמן ציטוט</span><b class="ltr">{e(h.get("quote_time"))}</b>'
             f'<span>{"שוק פתוח" if h.get("market_open") else "שוק סגור"} (A8)'
             f'{" · " + e(h["market_state"]) if h.get("market_state") else ""}</span></div>'
             f'<div><span>מודל עסקי</span><b class="ltr">{e(h.get("business_model") or "n/a")}</b>'
             f'<span class="ltr">{e(h.get("business_model_source"))}</span></div>'
             f'<div><span>סקטור / תעשייה / מדינה</span><span class="ltr">{e(h.get("sector"))} / '
             f'{e(h.get("industry"))} / {e(h.get("country"))}</span></div>'
             f'<div><span>שלמות נתונים</span><b>{r.completeness:.0f}%</b></div></div>')

    # verdict box
    p.append(f'<div class="verdict {vc}"><div class="big">{e(verdict_he(r))} '
             f'<span class="ltr muted">({e(r.verdict)})</span></div>')
    if r.eliminated_at:
        st = r.steps[r.eliminated_at - 1]
        p.append(f"<div>הסיבות בשלב {st.n} ({e(st.name)}):</div><ul>")
        for c in st.failed():
            why = c.note if c.note else f"threshold {c.threshold}"
            p.append(f'<li>{e(c.name)}: <span class="ltr">{e(c.value)}; {e(why)}</span></li>')
        p.append("</ul>")
        others = [s for s in r.steps if s.status == FAIL and s.n != r.eliminated_at]
        if others:
            p.append("<div>שלבים נוספים שנכשלו: " + ", ".join(f"{s.n}" for s in others) + "</div>")
    elif r.verdict == "INCOMPLETE":
        p.append("<div>אף שלב לא נכשל, אבל חסרים נתונים. ראו \"מה חסר\" למטה.</div>")
    else:
        p.append('<div class="en">"A company you could own for 20 years."</div>')
    p.append(f'<div class="muted">ניקוד: <span class="ltr">{e(score_text(r.score))} /130 · {e(r.score["band"])}</span></div>')
    p.append("</div>")

    if r.notes:
        p.append('<h3>הערות</h3><ul>' + "".join(f'<li class="ltr">{e(n)}</li>' for n in r.notes) + "</ul>")

    for st in r.steps:
        open_ = " open" if st.status in (FAIL, UNKNOWN) else ""
        p.append(f'<details{open_}><summary>{badge(st.status)} שלב {st.n}: {e(st.name)} '
                 f'<span class="en">{e(st.name_en)}</span></summary><div>')
        if st.quote:
            p.append(f'<p class="en">"{e(st.quote)}"</p>')
        if st.n == 6:
            p.append(scorecard_html(r.score))
        if st.n == 12:
            p.append(valuation_html(r.valuation, h))
        p.append(checks_table(st))
        for n in st.notes:
            p.append(f'<p class="en">{e(n)}</p>')
        p.append("</div></details>")

    p.append("<h3>מה חסר (שדות למלא בקובץ הידני)</h3>")
    if r.missing:
        p.append("<ul>" + "".join(f"<li><code>{e(r.ticker)}.{e(f)}</code></li>" for f in r.missing) + "</ul>")
    else:
        p.append("<p>אין שדות ידניים חסרים.</p>")
    if r.manual_errors:
        p.append("<p>ערכים לא תקינים בקובץ הידני (נחשבו כלא מולאו):</p><ul>"
                 + "".join(f'<li class="ltr">{e(x)}</li>' for x in r.manual_errors) + "</ul>")

    if r.verdict in ("SURVIVED ALL 12", "INCOMPLETE"):
        p.append(after_html(r))

    p.append("<h3>הנחות שהופעלו</h3><ul>")
    for a in r.assumptions:
        p.append(f'<li><b class="ltr">{e(a)}</b> <span class="ltr">{e(config.ASSUMPTIONS.get(a, ""))}</span></li>')
    p.append("</ul>")

    fx = h.get("fx") or {}
    p.append('<h3>נתונים ומקורות</h3><ul class="ltr">'
             f"<li>fetched {e(h.get('fetched_at'))} (cache {e(h.get('cache'))}); quote {e(h.get('quote_time'))}</li>"
             f"<li>currency: trading {e(fx.get('trading_currency'))}, financial {e(fx.get('financial_currency'))}"
             f"{'; statements FX ' + e(json.dumps(fx.get('statements'))) if fx.get('statements') else ''}"
             f"{'; to USD ' + e(json.dumps(fx.get('to_usd'))) if fx.get('to_usd') else ''}</li>")
    for err in r.errors:
        p.append(f"<li>fetch error: {e(err)}</li>")
    p.append("<li>yfinance labels used appear in each check's source column</li></ul>")
    p.append("</section>")
    return "".join(p)


def scorecard_html(sc) -> str:
    rows = ['<div class="tbl"><table><tr><th>#</th><th>קטגוריה</th><th>ערך</th><th>נקודות</th><th>מקור</th></tr>']
    for r in sc["rows"]:
        pts = "?" if r.points is None else r.points
        rows.append(f'<tr><td>{r.n}</td><td>{e(r.name_he)} <span class="en">{e(r.name)}</span></td>'
                    f'<td class="ltr">{e(r.value)}</td><td class="ltr"><b>{pts}</b></td><td class="ltr">{e(r.source)}</td></tr>')
    rows.append(f'<tr><td></td><td><b>סה"כ</b></td><td class="ltr" colspan="3"><b>{sc["computed"]} computed + '
                f'{sc["manual"]} manual = {sc["min"]}</b>'
                + ("" if sc["complete"] else f" · possible range {sc['min']}-{sc['max']}")
                + f' /130 (the document calls it 125) · {e(sc["band"])}</td></tr></table></div>')
    rows.append('<p class="en">*Subjective. Score these as harshly as you can.</p>'
                '<p class="en">100-125 "Exceptional. Once in a lifetime." · 75-100 "Watchlist. Investable." · '
                'below 75 "Absolute no-go"</p>'
                '<p class="en">"If you love a stock but it scores 75, the stock doesn\'t love you back."</p>')
    return "".join(rows)


def valuation_html(v, h) -> str:
    out = []
    if v.get("cases"):
        out.append('<div class="tbl"><table><tr><th>תרחיש</th><th>שיעור היוון</th><th>ערך למניה</th><th>מחיר</th>'
                   '<th>אפסייד</th><th>שווי הון</th><th>EV</th></tr>')
        names = {"bull": "שורי", "base": "בסיס", "bear": "דובי"}
        for k in ("bull", "base", "bear"):
            c = v["cases"][k]
            out.append(f'<tr><td>{names[k]}</td><td class="ltr">{c["rate"]:.0%}</td>'
                       f'<td class="ltr">{c["per_share"]:,.2f}</td><td class="ltr">{fmt(h["price"], "", 2)}</td>'
                       f'<td class="ltr">{c["upside"]:+.1%}</td><td class="ltr">{money(c["equity"])}</td>'
                       f'<td class="ltr">{money(c["ev"])}</td></tr>')
        out.append("</table></div>")
        flows = v["cases"]["base"]["flows"]
        out.append('<p class="ltr muted">base case flows: ' + " | ".join(
            f"Y{f['year']} rev {money(f['revenue'])} FCF {money(f['fcf'])}" for f in flows)
            + f" | terminal {money(v['cases']['base']['terminal'])} (4%, fixed)</p>")
    if v.get("reverse"):
        rv = v["reverse"]
        out.append(f'<p>DCF הפוך: <span class="ltr">implied {rv["implied"]:.1%} vs delivered {rv["delivered"]:.1%} '
                   f'→ gap {rv["gap"]:+.1%}</span> <span class="en">"The gap is where you make money."</span></p>')
    return "".join(out)


def after_html(r) -> str:
    title = "אחרי 12 השלבים" if r.verdict == "SURVIVED ALL 12" else "אחרי 12 השלבים (תבנית, לאחר השלמת הנתונים)"
    return (f"<h3>{title}</h3><ul>"
            "<li>קנייה הדרגתית: סכום קבוע, בתאריך קבוע, אוטומטי (DCA). אף פעם לא סכום חד פעמי למניה בודדת.</li>"
            "<li>לכתוב את היציאה לפני הקנייה: למה אני מחזיק ומה יגרום לי למכור "
            "(<code>after.why_i_own_it</code>, <code>after.what_would_make_me_sell</code>). "
            "הונאה: החוצה מיד. תזה שנשברת לאט: מכירה הדרגתית לאורך כ 18 חודשים. תנועת מחיר אף פעם אינה סיבה.</li>"
            "<li>בדיקה כל רבעון: להקשיב לשיחת הרווחים, לקרוא את המספרים הרבעוניים, ולהריץ את כרטיס הניקוד פעם בשנה. "
            "כשהמניה יורדת, לשאול שאלה אחת: האם השתנה משהו משמעותי בעסק?</li></ul>")


# ------------------------------------------------------------------ CSV / JSON
def csv_rows(results):
    rows = []
    for r in results:
        h = r.header
        row = {"ticker": r.ticker, "name": h["name"], "verdict": r.verdict, "eliminated_at": r.eliminated_at or "",
               "score_computed": r.score["computed"], "score_manual": r.score["manual"],
               "score_min": r.score["min"], "score_max": r.score["max"], "score_band": r.score["band"],
               "price": h["price"], "currency": h.get("currency"), "market_cap": h["market_cap"],
               "market_cap_usd": h["market_cap_usd"], "completeness_pct": round(r.completeness, 1),
               "quote_time": h.get("quote_time"), "business_model": h.get("business_model"),
               "missing_fields": "; ".join(r.missing)}
        for s in r.steps:
            row[f"s{s.n}_status"] = s.status
        for s in r.steps:
            for c in s.checks:
                row[f"s{s.n}.{c.id}.status"] = c.status
                row[f"s{s.n}.{c.id}.value"] = c.raw if c.raw is not None and not isinstance(c.raw, (dict, list)) else c.value
        rows.append(row)
    return rows


def write_csv(results, path: Path):
    rows = csv_rows(results)
    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads Hebrew correctly
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def write_json(results, raws: dict, path: Path, run_meta: dict):
    out = {"run": run_meta, "tickers": {}}
    for t, raw in raws.items():
        res = next((r for r in results if r.ticker == t), None)
        out["tickers"][t] = {
            "raw": raw,
            "checks": [{"step": s.n, "id": c.id, "status": c.status, "value": c.value, "source": c.source,
                        "assumptions": list(c.assumptions)} for s in res.steps for c in s.checks] if res else [],
        }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def write_all(results, raws, errors, reports_dir, run_meta) -> dict:
    d = Path(reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    paths = {"html": d / f"nash_report_{stamp}.html", "csv": d / f"nash_summary_{stamp}.csv",
             "json": d / f"nash_raw_{stamp}.json"}
    paths["html"].write_text(html_report(results, run_meta, errors), encoding="utf-8")
    write_csv(results, paths["csv"])
    write_json(results, raws, paths["json"], run_meta)
    return paths
