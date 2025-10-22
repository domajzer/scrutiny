# report_html.py
import argparse
import json
import re
import os
from datetime import datetime
from typing import Dict, Any, List, Iterable, Optional
from dominate import document, tags
from dominate.util import raw
import html 

from scrutiny.htmlutils import show_hide_div, show_all_button, hide_all_button, default_button
from scrutiny.interfaces import ContrastState 

TOOLTIP_TEXT = {
    ContrastState.MATCH: "Devices seem to match",
    ContrastState.WARN: "There seem to be some differences worth checking",
    ContrastState.SUSPICIOUS: "Devices probably don't match",
}
RESULT_TEXT = {
    ContrastState.MATCH: lambda x:
        "None of the modules raised suspicion during the verification process.",
    ContrastState.WARN: lambda x:
        f"There seem to be some differences worth checking. {x} module(s) report inconsistencies.",
    ContrastState.SUSPICIOUS: lambda x:
        f"{x} module(s) report suspicious differences between profiled and reference devices. "
        "The verification process may have been unsuccessful and compared devices are different.",
}

_id_pat = re.compile(r"[^A-Za-z0-9_-]+")
def safe_id(s: str) -> str:
    return _id_pat.sub("_", s)

def table(headers: Iterable[str], rows: Iterable[Iterable[Any]]):
    t = tags.table(cls="report-table")
    with t:
        thead = tags.thead()
        with thead:
            tr = tags.tr()
            for h in headers:
                tags.th(h)
        tbody = tags.tbody()
        with tbody:
            for r in rows:
                tr = tags.tr()
                for cell in r:
                    td = tags.td()
                    if cell is None:
                        continue
                    if hasattr(cell, "render"):
                        td.add(cell)
                    else:
                        td.add(str(cell))
    return t

def state_enum(s: str) -> ContrastState:
    try:
        return ContrastState[s]
    except Exception:
        return ContrastState.WARN

def render_status_dot(state: ContrastState):
    with tags.span(cls="dot " + state.name.lower()):
        tags.span(TOOLTIP_TEXT[state], cls="tooltiptext " + state.name.lower())

def badge(text: str, kind: str) -> tags.span:
    return tags.span(text, cls=f"badge badge-{kind}")

def bool_to_badge(value: Any) -> tags.span:
    if isinstance(value, bool):
        return badge("Supported", "ok") if value else badge("Unsupported", "bad")
    sval = str(value).strip().lower()
    if sval in {"true", "yes", "supported"}: return badge("Supported", "ok")
    if sval in {"false", "no", "unsupported"}: return badge("Unsupported", "bad")
    return badge("Unknown", "neutral")

def display_key(raw_key: Any, labels: Dict[str, str]) -> str:
    try:
        return labels.get(str(raw_key), str(raw_key))
    except Exception:
        return str(raw_key)

def fast_summary(stats: Dict[str, Any]) -> str:
    compared  = int(stats.get("compared", 0))
    changed   = int(stats.get("changed", 0))
    only_ref  = int(stats.get("only_ref", 0))
    only_test = int(stats.get("only_test", 0))
    return (f"Compared {compared} items. "
            f"Differences: {changed}. "
            f"Missing on profile: {only_ref}. "
            f"Extra on profile: {only_test}.")

# ---- helpers for grouped (set-mode) diffs/matches ----

def _filter_tuple_for_label(item: Any, key_label: str) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    filtered = {k: v for k, v in item.items() if str(v) != str(key_label)}
    return filtered if filtered else dict(item)

def _tuple_value_text(item: Any, key_label: str) -> str:
    if item is None:
        return ""
    if not isinstance(item, dict):
        return str(item)
    d = _filter_tuple_for_label(item, key_label)
    if len(d) == 1:
        k, v = next(iter(d.items()))
        return f"{k} {v}"
    return ", ".join(f"{k} {v}" for k, v in d.items())

def pair_group_changes(removed: List[Dict[str, Any]], added: List[Dict[str, Any]]):
    out = []
    r = removed[:]
    a = added[:]
    while r and a:
        out.append(("arrow", r.pop(0), a.pop(0)))
    for x in r:
        out.append(("removed", x, None))
    for y in a:
        out.append(("added", None, y))
    return out

def format_group_value(v: Any) -> tags.span:
    if v is None:
        return tags.span("matched", cls="badge badge-ok")
    if isinstance(v, dict):
        parts = []
        for f, vv in v.items():
            if isinstance(vv, (list, tuple, set)):
                parts.append(f"{f}: {', '.join(str(x) for x in vv)}")
            else:
                parts.append(f"{f}: {vv}")
        return tags.span("; ".join(parts))
    if isinstance(v, (list, tuple, set)):
        return tags.span(", ".join(str(x) for x in v))
    return tags.span(str(v))

def extract_buckets_for_report(section: Dict[str, Any]) -> Dict[str, Any]:
    labels: Dict[str, str] = section.get("key_labels", {}) or {}
    diffs = section.get("diffs", []) or []

    boolean_rows_raw = []
    string_rows_raw  = []
    missing_rows     = []
    extra_rows       = []
    grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    for d in diffs:
        field = d.get("field")
        key_raw = d.get("key")
        item_label = display_key(key_raw, labels)

        if field == "__presence__":
            if d.get("ref") and not d.get("test"):
                missing_rows.append([item_label, "present in reference only"])
            elif d.get("test") and not d.get("ref"):
                extra_rows.append([item_label, "present in profile only"])
            continue

        if field == "__group__":
            g = grouped.setdefault(str(key_raw), {"removed": [], "added": []})
            if d.get("ref") is not None and d.get("test") is None:
                g["removed"].append(d.get("ref"))
            elif d.get("ref") is None and d.get("test") is not None:
                g["added"].append(d.get("test"))
            continue

        ref_v, test_v = d.get("ref"), d.get("test")
        if isinstance(ref_v, bool) or isinstance(test_v, bool):
            boolean_rows_raw.append((item_label, field, ref_v, test_v))
        else:
            string_rows_raw.append((item_label, field, ref_v, test_v))

    for k, grp in grouped.items():
        item_label = display_key(k, labels)
        pairs = pair_group_changes(grp["removed"], grp["added"])
        for kind, rdict, tdict in pairs:
            if kind == "arrow":
                rd = _filter_tuple_for_label(rdict, item_label)
                td = _filter_tuple_for_label(tdict, item_label)
                keys = sorted(set(rd.keys()) | set(td.keys())) or ["set"]
                field_name = ", ".join(keys)
                string_rows_raw.append(
                    (item_label, field_name, _tuple_value_text(rdict, item_label), _tuple_value_text(tdict, item_label))
                )
            elif kind == "removed":
                missing_rows.append([item_label, _tuple_value_text(rdict, item_label)])
            else:
                extra_rows.append([item_label, _tuple_value_text(tdict, item_label)])

    distinct_fields = sorted({f for (_, f, _, _) in string_rows_raw})
    include_field_col = len(distinct_fields) > 1

    boolean_rows = []
    for (item, _field, ref_v, test_v) in sorted(boolean_rows_raw, key=lambda x: x[0]):
        boolean_rows.append([item, bool_to_badge(ref_v), bool_to_badge(test_v)])

    if include_field_col:
        string_rows = [[item, field, ref_v, test_v] for (item, field, ref_v, test_v) in sorted(string_rows_raw, key=lambda x: (x[0], x[1]))]
    else:
        string_rows = [[item, ref_v, test_v] for (item, _field, ref_v, test_v) in sorted(string_rows_raw, key=lambda x: x[0])]

    return {
        "boolean_rows": boolean_rows,
        "string_rows": string_rows,
        "string_include_field": include_field_col,
        "missing_rows": sorted(missing_rows, key=lambda x: x[0]),
        "extra_rows": sorted(extra_rows, key=lambda x: x[0]),
    }

def _num(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def _render_chart_svg(section_name: str, section: Dict[str, Any], idx: int):
    """
    Draw a simple paired horizontal bar chart for rows that have numeric ref/test averages.
    Uses inline SVG emitted as a raw string (no dominate.svg dependency).
    """
    rows = section.get("chart_rows") or []
    if not rows:
        return

    rpt = (section.get("report") or {})
    xlab = rpt.get("x_axis") or "Reference avg (ms)"
    ylab = rpt.get("y_axis") or "Profile avg (ms)"

    def _num(x):
        try:
            return float(x)
        except Exception:
            return None

    data = []
    for r in rows:
        ra = _num(r.get("ref_avg"))
        ta = _num(r.get("test_avg"))
        if ra is None or ta is None:
            continue
        label = r.get("key", "")
        status = r.get("status", "")
        data.append((label, ra, ta, status))

    if not data:
        return

    # Layout constants
    left_pad   = 220       # space for algorithm labels
    right_pad  = 30
    top_pad    = 30
    bar_h      = 14
    gap        = 10        # gap between paired bars (same algorithm)
    row_gap    = 18        # gap between algorithms
    pair_h     = bar_h * 2 + gap
    chart_w    = 900
    chart_h    = top_pad + len(data) * (pair_h + row_gap) + 40

    # Scaling
    max_val = max(max(ra, ta) for _, ra, ta, _ in data)
    if max_val <= 0:
        max_val = 1.0
    scale = (chart_w - left_pad - right_pad) / max_val

    # Colors
    col_ref  = "#6baed6"   # blue-ish
    col_tst  = "#31a354"   # green-ish
    col_axes = "#555"

    # Build SVG as a string
    svg_id = f"svg_chart_{safe_id(section_name)}_{idx}"
    parts = []
    parts.append(
        f'<svg id="{svg_id}" width="{chart_w}" height="{chart_h}" '
        f'style="max-width:100%;height:auto;border:1px solid #eee;background:#fff">'
    )

    # Axis label
    parts.append(
        f'<text x="{left_pad}" y="20" fill="{col_axes}" font-size="12">'
        f'{html.escape(xlab)} / {html.escape(ylab)}</text>'
    )

    # X ticks (0, 25%, 50%, 75%, 100%)
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        val = max_val * frac
        x = left_pad + val * scale
        parts.append(
            f'<line x1="{x:.2f}" y1="{top_pad-5}" x2="{x:.2f}" y2="{chart_h-20}" stroke="#f0f0f0"/>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{top_pad-10}" fill="{col_axes}" font-size="10" text-anchor="middle">{val:.2f}</text>'
        )

    # Bars + labels
    y = top_pad
    for (label, ra, ta, status) in data:
        elabel = html.escape(str(label))
        # Left-side label (vertically centered between the two bars)
        parts.append(
            f'<text x="10" y="{y + bar_h + gap/2:.2f}" fill="{col_axes}" font-size="12">{elabel}</text>'
        )
        # Reference bar
        w_ref = max(0.0, ra * scale)
        parts.append(
            f'<rect x="{left_pad}" y="{y}" width="{w_ref:.2f}" height="{bar_h}" fill="{col_ref}" opacity="0.9" />'
        )
        # Profile bar
        w_tst = max(0.0, ta * scale)
        parts.append(
            f'<rect x="{left_pad}" y="{y + bar_h + gap:.2f}" width="{w_tst:.2f}" height="{bar_h}" fill="{col_tst}" opacity="0.9" />'
        )
        # Values
        parts.append(
            f'<text x="{left_pad + w_ref + 4:.2f}" y="{y + bar_h - 2}" fill="{col_axes}" font-size="10">{ra:.2f} ms</text>'
        )
        parts.append(
            f'<text x="{left_pad + w_tst + 4:.2f}" y="{y + 2*bar_h + gap - 2:.2f}" fill="{col_axes}" font-size="10">{ta:.2f} ms</text>'
        )
        # Optional status hint at far right
        if status in {"mismatch", "skipped"}:
            parts.append(
                f'<text x="{chart_w - right_pad}" y="{y + bar_h}" fill="#888" font-size="10" text-anchor="end">{html.escape(status)}</text>'
            )

        y += pair_h + row_gap

    # Legend
    leg_y = chart_h - 18
    parts.append(f'<rect x="{left_pad}" y="{leg_y-10}" width="10" height="10" fill="{col_ref}" />')
    parts.append(f'<text x="{left_pad + 16}" y="{leg_y-2}" fill="{col_axes}" font-size="11">Reference</text>')
    parts.append(f'<rect x="{left_pad + 100}" y="{leg_y-10}" width="10" height="10" fill="{col_tst}" />')
    parts.append(f'<text x="{left_pad + 116}" y="{leg_y-2}" fill="{col_axes}" font-size="11">Profile</text>')

    parts.append('</svg>')
    svg_markup = "".join(parts)

    # Wrap in a collapsible block; add a small hint above
    cdiv = show_hide_div(f"section_{idx}_chart_svg", hide=False)
    with cdiv:
        tags.h3("Chart: Reference vs Profile (bar chart)")
        tags.p("Each algorithm shows two bars: reference (blue) and profile (green). "
               "Length = avg time (ms); shorter is faster.", cls="hint")
        # Inject raw SVG
        tags.div().add(raw(svg_markup))

def _render_chart_table(section_name: str, section: Dict[str, Any], idx: int):
    rows = section.get("chart_rows") or []
    if not rows:
        return

    rpt = (section.get("report") or {})
    xlab = rpt.get("x_axis") or "Reference avg (ms)"
    ylab = rpt.get("y_axis") or "Profile avg (ms)"

    divname = f"section_{idx}_chart"
    cdiv = show_hide_div(divname, hide=False)
    with cdiv:
        tags.h3("Chart: Reference vs Profile (table view)")
        tags.p("Δ% is (Profile - Reference) / Reference × 100. Rows marked 'skipped' follow the fast-op rules; "
               "'error' rows indicate both sides failed; 'error_mismatch' indicates different errors.", cls="hint")

        def fmt(v, digits=2):
            if v is None: return ""
            try:
                return f"{float(v):.{digits}f}"
            except Exception:
                return str(v)

        hdrs = ["Algorithm", xlab, ylab, "Δ ms", "Δ %", "Status", "Note"]
        body = []
        for r in rows:
            body.append([
                r.get("key", ""),
                fmt(r.get("ref_avg")),
                fmt(r.get("test_avg")),
                fmt(r.get("delta_ms")),
                fmt(r.get("delta_pct")),
                r.get("status", ""),
                r.get("note", ""),
            ])
        table(hdrs, body)


def render_module_card(section_name: str, section: Dict[str, Any], idx: int):
    state = state_enum(section.get("result", "WARN"))
    divname = f"section_{idx}"

    tags.h2(f"Module: {section_name}")
    with tags.div():
        render_status_dot(state)
        tags.span(f"  {state.name}", style="margin-left:8px; font-weight:bold;")

    stats_display = section.get("stats_display") or section.get("stats", {})
    tags.p(fast_summary(stats_display))

    types = (section.get("report", {}) or {}).get("types")
    types = {t.lower() for t in types} if types else {"table"}

    if "chart" in types:
        _render_chart_svg(section_name, section, idx)
        _render_chart_table(section_name, section, idx)

    buckets = extract_buckets_for_report(section) if "table" in types else {
        "boolean_rows": [], "string_rows": [], "string_include_field": False,
        "missing_rows": [], "extra_rows": []
    }

    if "table" in types and buckets["boolean_rows"]:
        bdiv = show_hide_div(f"{divname}_bool", hide=False)
        with bdiv:
            tags.h3("Boolean / binary differences")
            tags.p("If a capability is supported by the reference but not by the profile (or vice versa), the cards likely do not match.", cls="hint")
            table(["Item", "Reference", "Profile"], buckets["boolean_rows"])

    if "table" in types and buckets["string_rows"]:
        sdiv = show_hide_div(f"{divname}_strings", hide=False)
        with sdiv:
            tags.h3("Differences in string fields")
            headers = ["Item", "Field", "Reference", "Profile"] if buckets["string_include_field"] else ["Item", "Reference", "Profile"]
            table(headers, buckets["string_rows"])

    if "table" in types and buckets["missing_rows"]:
        mdiv = show_hide_div(f"{divname}_missing", hide=True)
        with mdiv:
            tags.h3("Missing on profile (present in reference)")
            table(["Item", "Detail"], buckets["missing_rows"])

    if "table" in types and buckets["extra_rows"]:
        ediv = show_hide_div(f"{divname}_extra", hide=True)
        with ediv:
            tags.h3("Extra on profile (absent in reference)")
            table(["Item", "Detail"], buckets["extra_rows"])

    if section.get("matches"):
        mv = show_hide_div(f"{divname}_matches", hide=True)
        with mv:
            tags.h3("Matches")
            rows = []
            labels = section.get("key_labels", {}) or {}
            for m in section["matches"]:
                item  = display_key(m.get("key"), labels)
                field = m.get("field")
                val   = m.get("value")

                if field == "__group__":
                    pretty_field = "set"
                    val_node = format_group_value(val)
                else:
                    pretty_field = field
                    val_node = bool_to_badge(val) if isinstance(val, bool) else tags.span("" if val is None else str(val))

                rows.append([item, pretty_field, val_node])
            table(["Item", "Field", "Value"], rows)

    tags.hr()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verification-profile",
                        help="Input verification JSON produced by verify.py",
                        action="store", metavar="file", required=True)
    parser.add_argument("-o", "--output-file",
                        help="Name of output HTML",
                        action="store", metavar="outfile",
                        required=False, default="comparison.html")
    parser.add_argument("-e", "--exclude-style-and-scripts",
                        help="Link CSS/JS instead of inlining",
                        action="store_true")
    args = parser.parse_args()

    with open("data/script.js", "r", encoding="utf-8") as js, \
         open("data/style.css",  "r", encoding="utf-8") as css:
        script = "\n" + js.read() + "\n"
        style  = "\n" + css.read() + "\n"

    with open(args.verification_profile, "r", encoding="utf-8") as f:
        report = json.load(f)

    ref_name  = report.get("reference_name", "reference")
    prof_name = report.get("profile_name", "profile")
    overall_state = state_enum(report.get("overall", "WARN"))

    suspicions = sum(
        1 for s in report.get("sections", {}).values()
        if state_enum(s.get("result", "WARN")).value >= ContrastState.WARN.value
    )

    doc = document(title="Comparison of smart cards")

    with doc.head:
        if args.exclude_style_and_scripts:
            tags.link(rel="stylesheet", href="style.css")
            tags.script(type="text/javascript", src="script.js")
        else:
            tags.style(raw(style))
            tags.script(raw(script), type="text/javascript")

    with doc:
        tags.button("Back to Top", onclick="backToTop()", id="topButton", cls="floatingbutton")

        # Intro
        intro_div = tags.div(id="intro")
        with intro_div:
            tags.h1(f"Verification of {prof_name} against {ref_name}")
            tags.p("Generated on: " + datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
            tags.p("Generated from: " + args.verification_profile)
            tags.h2("Verification results")
            tags.h4("Ordered results from tested modules:")

        with tags.div(id="modules"):
            for section_name, sec in report.get("sections", {}).items():
                state = state_enum(sec.get("result", "WARN"))
                with intro_div:
                    render_status_dot(state)

        # Sections
        for idx, (section_name, sec) in enumerate(report.get("sections", {}).items()):
            render_module_card(section_name, sec, idx)

        with intro_div:
            tags.br()
            tags.p(RESULT_TEXT[overall_state](suspicions))
            tags.h3("Quick visibility settings")
            show_all_button()
            hide_all_button()
            default_button()

    out_dir = "results"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, os.path.basename(args.output_file))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(str(doc))
