# report_html.py
import argparse
import json
import re
import os 
from datetime import datetime
from dominate import document, tags
from dominate.util import raw

from scrutiny.htmlutils import show_hide_div, show_all_button, hide_all_button, default_button
from scrutiny.interfaces import ContrastState  # used to keep your existing CSS classes/colors

TOOLTIP_TEXT = {
    ContrastState.MATCH: "Devices seem to match",
    ContrastState.WARN: "There seem to be some differences worth checking",
    ContrastState.SUSPICIOUS: "Devices probably don't match"
}

RESULT_TEXT = {
    ContrastState.MATCH: lambda x:
        "None of the modules raised suspicion during the verification process.",
    ContrastState.WARN: lambda x:
        f"There seem to be some differences worth checking. {x} module(s) report inconsistencies.",
    ContrastState.SUSPICIOUS: lambda x:
        f"{x} module(s) report suspicious differences between profiled and reference devices. "
        "The verification process may have been unsuccessful and compared devices are different."
}

def state_enum(s: str) -> ContrastState:
    try:
        return ContrastState[s]
    except Exception:
        return ContrastState.WARN

def table(headers, rows):
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
                    tags.td("" if cell is None else str(cell))
    return t

_id_pat = re.compile(r"[^A-Za-z0-9_-]+")
def safe_id(s: str) -> str:
    return _id_pat.sub("_", s)

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

        # Dot legend / worst state
        with tags.div(id="modules"):
            for section_name, sec in report.get("sections", {}).items():
                state = state_enum(sec.get("result", "WARN"))
                with intro_div:
                    with tags.span(cls="dot " + state.name.lower()):
                        tags.span(TOOLTIP_TEXT[state], cls="tooltiptext " + state.name.lower())

        # Sections
        for idx, (section_name, sec) in enumerate(report.get("sections", {}).items()):
            state = state_enum(sec.get("result", "WARN"))
            divname = f"section_{idx}"

            # Section header + summary
            tags.h2(f"{section_name} – {state.name}")
            st = sec.get("stats", {})
            stat_headers = ["diff_count", "compared", "changed", "matched", "only_ref", "only_test"]
            tags.div(table(stat_headers, [[st.get(h, 0) for h in stat_headers]]))

            # Diffs (collapsible)
            diffs = sec.get("diffs", [])
            if diffs:
                diffs_div = show_hide_div(f"{divname}_diffs", hide=True)  # no title kwarg
                with diffs_div:
                    tags.h3("Diffs")
                    headers = ["key", "field", "ref", "op", "test"]
                    rows = [[d.get("key"), d.get("field"), d.get("ref"), d.get("op"), d.get("test")] for d in diffs]
                    table(headers, rows)

            # Matches by field (collapsible groups)
            by_field = sec.get("by_field", {})
            if by_field:
                matches_root = show_hide_div(f"{divname}_matches", hide=True)  # no title kwarg
                with matches_root:
                    tags.h3("Matches by field")
                    for field_name, grp in sorted(by_field.items(), key=lambda kv: kv[0]):
                        sub = show_hide_div(f"{divname}_field_{safe_id(field_name)}", hide=True)
                        with sub:
                            tags.h4(field_name)
                            gstats = grp.get("stats", {})
                            tags.p(f"changed={gstats.get('changed',0)}, matched={gstats.get('matched',0)}, compared={gstats.get('compared',0)}")
                            matches = grp.get("matches", [])
                            if matches:
                                headers = ["key", "value"]
                                rows = [[m.get("key"), m.get("value")] for m in matches]
                                table(headers, rows)

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