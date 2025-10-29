from __future__ import annotations
from typing import Dict, Any, List
from scrutiny.interfaces import ContrastState


# --------------------------- helpers: enums & severity ---------------------------

_STATE_TO_STR = {
    ContrastState.MATCH: "MATCH",
    ContrastState.WARN: "WARN",
    ContrastState.SUSPICIOUS: "SUSPICIOUS",
}
_ORDER = {"MATCH": 0, "WARN": 1, "SUSPICIOUS": 2}


def _state_to_str(x) -> str:
    if isinstance(x, ContrastState):
        return _STATE_TO_STR[x]
    if isinstance(x, str):
        up = x.upper()
        if up in _ORDER:
            return up
    return "WARN"


def _max_state(a: str, b: str) -> str:
    return a if _ORDER.get(a, 1) >= _ORDER.get(b, 1) else b


def compute_severity(meta: dict, changed: int, compared: int) -> str:
    if compared == 0 or changed == 0:
        return "MATCH"

    thr_ratio = meta.get("threshold_ratio", None)
    thr_count = meta.get("threshold_count", None)

    if isinstance(thr_ratio, (int, float, str)):
        try:
            thr_ratio = float(thr_ratio)
        except Exception:
            thr_ratio = None
    if isinstance(thr_count, (int, float, str)):
        try:
            thr_count = int(thr_count)
        except Exception:
            thr_count = None

    if isinstance(thr_ratio, float) and 0 <= thr_ratio <= 1 and compared > 0:
        ratio = changed / float(compared)
        return "SUSPICIOUS" if ratio >= float(thr_ratio) else "WARN"

    if isinstance(thr_count, int) and thr_count > 0:
        return "SUSPICIOUS" if changed >= thr_count else "WARN"

    return "WARN"


# --------------------------- helpers: types & stats ---------------------------

def _default_types(has_table: bool, has_chart: bool) -> List[str]:
    out: List[str] = []
    if has_table:
        out.append("table")
    if has_chart:
        out.append("chart")
    return out or ["table"]


def _tally_stats(diffs: List[Dict[str, Any]], matches: List[Dict[str, Any]]) -> Dict[str, int]:
    only_ref = 0
    only_test = 0
    changed = 0

    for d in diffs or []:
        fld = d.get("field")
        if fld == "__presence__":
            r = d.get("ref")
            t = d.get("test")
            if isinstance(r, bool) and isinstance(t, bool):
                if r and not t:
                    only_ref += 1
                elif t and not r:
                    only_test += 1
                else:
                    changed += 1
            else:
                changed += 1
        else:
            changed += 1

    matched = len(matches or [])
    compared = changed + matched + only_ref + only_test

    return {
        "compared": compared,
        "changed": changed,
        "matched": matched,
        "only_ref": only_ref,
        "only_test": only_test,
    }


def _merge_severity_meta(schema: Dict[str, Any], section_name: str, section_res: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    if isinstance(schema, dict):
        cmp_root = schema.get("compare", {})
        if isinstance(cmp_root, dict):
            sec = cmp_root.get(section_name, {})
            if isinstance(sec, dict):
                sev = sec.get("severity", {})
                if isinstance(sev, dict):
                    out.update(sev)
        sections_root = schema.get("sections", {})
        if isinstance(sections_root, dict):
            sec = sections_root.get(section_name, {})
            if isinstance(sec, dict):
                sev = sec.get("severity", {})
                if isinstance(sev, dict):
                    out.update(sev)

    rep = section_res.get("report", {})
    if isinstance(rep, dict):
        sev = rep.get("severity", {})
        if isinstance(sev, dict):
            out.update(sev)

    sev2 = section_res.get("severity", {})
    if isinstance(sev2, dict):
        out.update(sev2)

    return out


# --------------------------- main entrypoint ---------------------------

def assemble_report(
    *,
    schema: Dict[str, Any],
    compare_results: Dict[str, Dict[str, Any]],
    reference_name: str,
    profile_name: str,
    section_rows: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    sections_out: Dict[str, Any] = {}
    overall = "MATCH"

    for name, res in (compare_results or {}).items():
        diffs = res.get("diffs", []) or []
        matches = res.get("matches", []) or []

        # Promote artifacts.chart_rows -> chart_rows
        artifacts = res.get("artifacts", {}) or {}
        chart_rows = res.get("chart_rows")
        if chart_rows is None:
            chart_rows = artifacts.get("chart_rows", []) or []
        # normalize
        if not isinstance(chart_rows, list):
            chart_rows = []

        # 1) Stats (prefer provided; recompute if zero but rows exist)
        provided_stats = res.get("stats")
        if isinstance(provided_stats, dict):
            stats = {
                "compared": int(provided_stats.get("compared", 0) or 0),
                "changed": int(provided_stats.get("changed", 0) or 0),
                "matched": int(provided_stats.get("matched", 0) or 0),
                "only_ref": int(provided_stats.get("only_ref", 0) or 0),
                "only_test": int(provided_stats.get("only_test", 0) or 0),
            }
            if (stats["compared"] == 0 and (diffs or matches)):
                stats = _tally_stats(diffs, matches)
        else:
            stats = _tally_stats(diffs, matches)

        # 2) Severity thresholds
        sev_meta = _merge_severity_meta(schema, name, res)

        # 3) Result (recompute for consistency)
        result = compute_severity(sev_meta, stats["changed"], stats["compared"])

        # 4) Report config (types derived from presence of data unless explicitly set)
        explicit_types = None
        rep_cfg = dict(res.get("report") or {})
        if isinstance(rep_cfg.get("types"), list) and rep_cfg["types"]:
            explicit_types = [str(t) for t in rep_cfg["types"]]
        rep_cfg["types"] = explicit_types or _default_types(
            has_table=bool(diffs or matches),
            has_chart=bool(chart_rows),
        )

        # 5) Labels passthrough
        key_labels = res.get("key_labels") or {}

        # 6) Assemble section
        section_obj = {
            "result": result,
            "stats": stats,
            "stats_display": dict(stats),
            "key_labels": key_labels,
            "diffs": diffs,
            "matches": matches,
            "chart_rows": chart_rows,
            "report": rep_cfg,
        }
        sections_out[name] = section_obj
        overall = _max_state(overall, result)

    out = {
        "reference_name": reference_name,
        "profile_name": profile_name,
        "overall": overall,
        "sections": sections_out,
        "meta": {
            "generated_by": "assemble_report",
            "schema_title": schema.get("title") if isinstance(schema, dict) else None,
        },
    }
    return out
