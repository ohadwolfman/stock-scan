"""nash_manual.yaml: the human judgements the document requires. null = not filled = UNKNOWN.

--init-manual creates or extends the file without overwriting filled values. Each ticker block
starts with a sentinel line so blocks of tickers not in the current run are kept verbatim.
"""
from __future__ import annotations

import copy
import json
import re
import textwrap
from pathlib import Path

import yaml

import config

SKIP_ZONES = ("small_cap", "chinese", "commodity", "airline", "seasonal", "startup")
SCORE_FIELDS = ("moat", "ceo", "recession_proof_pricing_power", "secular_trend", "culture_mission", "talent")

SCHEMA = {
    "founding_year": None,
    "business_model_type": None,
    "skip_zones": {k: None for k in SKIP_ZONES},
    "step1": {"trend_name": "", "paying_customers": None, "sustainable_growth": None, "moat_not_commodity": None,
              "regulatory_tailwind": None, "real_world_adoption": None, "built_for_trend": None,
              "market_story": "", "what_it_is_becoming": "", "has_gap": None},
    "step2_valid_reason": None,
    "step3": {"ceo_team_track_record": None, "no_regulatory_legal_overhang": None},
    "step4": {"provides": "", "helps": "", "achieve": "", "charges": "", "sentence_clean": None,
              "pain": "", "who_and_why": "", "why_us": ""},
    "step5": {"broad_market": None, "checked_market_size_myself": None, "market_big_enough": None, "note": ""},
    "step6": {k: None for k in SCORE_FIELDS},
    "step7": {"net_dollar_retention_pct": None, "revenue_segments_note": ""},
    "step8": {"peers": []},
    "step9": {"types": [], "getting_weaker": None, "why_customers_stay": "", "copyable_in_a_year": None,
              "margin_proves_it": None},
    "step10": {"execution_track_record": None, "skin_in_the_game": None, "ten_years_in_role": None,
               "capital_allocation": None, "straight_answers": None, "consistent_beats": None,
               "great_people_want_to_work": None, "results_not_excuses": None,
               "clown_ceo": None, "co_ceo": None, "acquisition_spree": None},
    "step11": {"bear_reasons": [], "read_bear_analysis": None, "bear_case": "", "can_live_with_it": None,
               "fraud_or_accounting_suspicion": None, "auditor_change": None,
               "insiders_selling_hard": None, "nonstop_media_hype": None},
    "step12": {"growth_trim_override": None},
    "after": {"why_i_own_it": "", "what_would_make_me_sell": ""},
}
FIELD_COMMENTS = {
    "business_model_type": "software | subscription | mature | hardware | bank | early_growth | other",
    "skip_zones": "true/false overrides auto-detection; seasonal is manual only",
    "step2_valid_reason": "infrastructure_leverage | path_to_profitability | none",
    "step6": "0 | 5 | 10 each. *Subjective. Score these as harshly as you can.",
    "step9": "types: " + ", ".join(config.MOAT_TYPES),
}
SENTINEL = "# ==== {} ===="
SENTINEL_RE = re.compile(r"^# ==== (\S+) ====\s*$")


def normalize_ticker(t: str) -> str:
    return t.strip().upper()


def _merge(schema, data):
    if isinstance(schema, dict):
        data = data if isinstance(data, dict) else {}
        out = {k: _merge(v, data.get(k)) for k, v in schema.items()}
        for k, v in data.items():  # keep unknown keys so nothing typed by hand is lost
            out.setdefault(k, v)
        return out
    return copy.deepcopy(schema) if data is None else data


def load(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {normalize_ticker(str(k)): _merge(SCHEMA, v) for k, v in data.items()}


def blank() -> dict:
    return copy.deepcopy(SCHEMA)


def is_filled(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def validate(ticker: str, d: dict) -> list[str]:
    """Problems that make a value unusable. Invalid values are treated as not filled."""
    errs = []
    bmt = d.get("business_model_type")
    if bmt is not None and bmt not in config.BUSINESS_MODEL_TYPES:
        errs.append(f"{ticker}.business_model_type '{bmt}' not in {config.BUSINESS_MODEL_TYPES}")
        d["business_model_type"] = None
    r = d.get("step2_valid_reason")
    if r is not None and r not in (*config.STEP2_VALID_REASONS, "none"):
        errs.append(f"{ticker}.step2_valid_reason '{r}' invalid")
        d["step2_valid_reason"] = None
    for k in SCORE_FIELDS:
        v = d["step6"].get(k)
        if v is not None and v not in config.MANUAL_SCORE_VALUES:
            errs.append(f"{ticker}.step6.{k} = {v}: must be 0, 5 or 10")
            d["step6"][k] = None
    types = d["step9"].get("types") or []
    bad = [t for t in types if t not in config.MOAT_TYPES]
    if bad:
        errs.append(f"{ticker}.step9.types unknown {bad}; allowed {config.MOAT_TYPES}")
        d["step9"]["types"] = [t for t in types if t in config.MOAT_TYPES]
    fy = d.get("founding_year")
    if fy is not None and not (isinstance(fy, int) and 1600 < fy < 2100):
        errs.append(f"{ticker}.founding_year '{fy}' is not a year")
        d["founding_year"] = None
    for section, fields in SCHEMA.items():
        if not isinstance(fields, dict):
            continue
        for k, default in fields.items():
            v = d[section].get(k)
            if default is None and v is not None and section not in ("step6", "step7", "step12") \
                    and not isinstance(v, bool):
                errs.append(f"{ticker}.{section}.{k} = {v!r}: expected true/false")
                d[section][k] = None
    for k in ("net_dollar_retention_pct", ):
        v = d["step7"].get(k)
        if v is not None and not isinstance(v, (int, float)):
            errs.append(f"{ticker}.step7.{k} must be a number")
            d["step7"][k] = None
    v = d["step12"].get("growth_trim_override")
    if v is not None and not (isinstance(v, (int, float)) and 0 <= v < 1):
        errs.append(f"{ticker}.step12.growth_trim_override must be a fraction 0..1 (0.25 = 25%)")
        d["step12"]["growth_trim_override"] = None
    return errs


class Manual:
    """Accessor that records which manual fields were needed but not filled."""

    def __init__(self, ticker: str, data: dict | None):
        self.ticker = ticker
        self.d = _merge(SCHEMA, data or {})
        self.errors = validate(ticker, self.d)
        self.missing: list[str] = []

    def get(self, path: str, required=True):
        cur = self.d
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if required and not is_filled(cur) and path not in self.missing:
            self.missing.append(path)
        return cur

    def peek(self, path: str):
        return self.get(path, required=False)


# ------------------------------------------------------------------ writing the file
def _scalar(v) -> str:
    return json.dumps(v, ensure_ascii=False)  # JSON scalars and flow lists are valid YAML


def _emit(d: dict, indent: int, comments: dict) -> list[str]:
    lines = []
    pad = " " * indent
    for k, v in d.items():
        for c in comments.get(k, []):
            lines.append(f"{pad}# {c}")
        tail = f"  # {FIELD_COMMENTS[k]}" if k in FIELD_COMMENTS and not isinstance(v, dict) else ""
        if isinstance(v, dict):
            if k in FIELD_COMMENTS:
                lines.append(f"{pad}# {FIELD_COMMENTS[k]}")
            lines.append(f"{pad}{k}:")
            lines.extend(_emit(v, indent + 2, {}))
        else:
            lines.append(f"{pad}{k}: {_scalar(v)}{tail}")
    return lines


def render_block(ticker: str, data: dict, header_hints: list[str], field_hints: dict) -> str:
    out = [SENTINEL.format(ticker)]
    for h in header_hints:
        for w in textwrap.wrap(str(h), 110) or [""]:
            out.append(f"# {w}")
    out.append(f"{ticker}:")
    out.extend(_emit(data, 2, field_hints))
    return "\n".join(out) + "\n"


def _split_blocks(text: str) -> dict:
    blocks, cur, buf = {}, None, []
    for line in text.splitlines():
        m = SENTINEL_RE.match(line)
        if m:
            if cur:
                blocks[cur] = "\n".join(buf) + "\n"
            cur, buf = m.group(1), [line]
        elif cur:
            buf.append(line)
    if cur:
        blocks[cur] = "\n".join(buf) + "\n"
    return blocks


def init_manual(path, tickers: list[str], hints: dict) -> tuple[int, int]:
    """Create or extend the manual file. Filled values are never overwritten.
    hints[ticker] = {"header": [...], "fields": {"step10": [...], ...}}. Returns (added, updated)."""
    p = Path(path)
    existing = load(p)
    old_text = p.read_text(encoding="utf-8") if p.exists() else ""
    old_blocks = _split_blocks(old_text)
    order = list(existing.keys()) + [t for t in tickers if t not in existing]
    added = updated = 0
    parts = ["# Nash 12-step manual inputs. null = not filled (the check stays UNKNOWN).\n"
             "# Created by nash_screen.py --init-manual. Filled values are never overwritten.\n"]
    for t in order:
        if t in tickers:
            h = hints.get(t, {})
            data = existing.get(t) or blank()
            parts.append(render_block(t, data, h.get("header", []), h.get("fields", {})))
            added += t not in existing
            updated += t in existing
        elif t in old_blocks:
            parts.append(old_blocks[t])
        else:
            parts.append(render_block(t, existing[t], [], {}))
    p.write_text("\n".join(parts), encoding="utf-8")
    return added, updated
