import sys
import argparse
import json
import os
import subprocess

from scrutiny.schemaloader import SchemaLoader
from scrutiny.ingest import JsonParser
from scrutiny.javacard.modules.comparator_basic import BasicComparator
from scrutiny.javacard.modules.algperf_comparator import AlgPerfComparator
from scrutiny import logging as slog

COMPARATORS = {
    "basic": BasicComparator,
    "algperf": AlgPerfComparator,
}

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

def _group_by_field(diffs_struct, matches_struct):
    out = {}
    def bucket(f):
        b = out.get(f)
        if b is None:
            b = {"stats": {"changed": 0, "matched": 0, "compared": 0},
                 "diffs": [], "matches": []}
            out[f] = b
        return b

    for d in diffs_struct:
        f = d.get("field", "__unknown__")
        b = bucket(f)
        b["diffs"].append(d)
        if f != "__presence__":
            b["stats"]["changed"] += 1
            b["stats"]["compared"] += 1

    for m in matches_struct:
        f = m.get("field", "__unknown__")
        b = bucket(f)
        b["matches"].append(m)
        if f != "__presence__":
            b["stats"]["matched"] += 1
            b["stats"]["compared"] += 1

    return out

def compare_schema_section(section: str, cfg: dict, data_ref: dict, data_tst: dict, *, emit_matches: bool) -> dict:
    data      = cfg.get("data", {}) or {}
    report    = cfg.get("report", {}) or {}
    component = cfg.get("component", {}) or {}
    target    = cfg.get("target", {}) or {}

    fields_norm   = data.get("record_schema") or {}
    comp_key      = (component.get("comparator") or "basic").lower()
    match_key     = component["match_key"]
    show_key      = component.get("show_key", match_key)
    want_match    = emit_matches or bool(component.get("include_matches", False))

    metadata = {
        "comparator": comp_key,
        "match_key": match_key,
        "show_key": show_key,
        "include_matches": bool(component.get("include_matches", False)),
        "threshold_ratio": component.get("threshold_ratio", None),
        "threshold_count": component.get("threshold_count", None),
        **target,
    }

    slog.log_info(f"  rows: ref={len(data_ref.get(section, []))} test={len(data_tst.get(section, []))}")
    slog.log_info(f"  match_key: {match_key}")
    slog.log_info(f"  n_fields: {len(list(fields_norm.keys()))}")

    Comparator = COMPARATORS.get(comp_key, BasicComparator)
    comp = Comparator(
        schema={section: {"fields": fields_norm, "metadata": metadata}},
        reference={section: data_ref.get(section, [])},
        tested={section:   data_tst.get(section, [])},
    )

    detailed = comp.compare_detailed(key_field=match_key, metadata=metadata, return_matches=want_match)

    diffs   = detailed["diffs"].get(section, [])
    matches = detailed.get("matches", {}).get(section, []) if want_match else []
    counts_field = detailed["counts"].get(section, {"compared": 0, "changed": 0, "matched": 0, "only_ref": 0, "only_test": 0})
    counts_items = (detailed.get("counts_items") or {}).get(section, None)
    labels       = (detailed.get("labels") or {}).get(section, {})
    chart_rows   = (detailed.get("chart") or {}).get(section, [])  # <-- added

    display_counts = counts_items if counts_items else counts_field
    result_label = compute_severity(metadata, changed=display_counts["changed"], compared=display_counts["compared"])

    diffs_struct = [
        {"key": n, "field": f, "ref": rv, "op": op, "test": tv}
        for (n, f, rv, op, tv) in diffs
    ]
    matches_struct = [
        {"key": n, "field": f, "value": v}
        for (n, f, v) in matches
    ] if want_match else []

    by_field = _group_by_field(diffs_struct, matches_struct)

    report_cfg = {"types": report.get("types", None)}
    for k, v in report.items():
        if k != "types":
            report_cfg[k] = v

    return {
        "comparator": comp_key,
        "result": result_label,
        "report": report_cfg,
        "stats": {
            "diff_count": len(diffs),
            "compared": counts_field["compared"],
            "changed": counts_field["changed"],
            "matched": counts_field["matched"],
            "only_ref": counts_field["only_ref"],
            "only_test": counts_field["only_test"],
        },
        "stats_display": display_counts,  
        "diffs": diffs_struct,
        **({"matches": matches_struct} if want_match else {}),
        "key_labels": labels,
        "by_field": by_field,
        "chart_rows": chart_rows, 
    }

def main():
    p = argparse.ArgumentParser(description="YAML-driven verification (schema v0.1, defaults, thresholds).")
    p.add_argument("-s", "--schema",    required=True, help="Path to structure.yml")
    p.add_argument("-r", "--reference", required=True, help="Path to the reference JSON file")
    p.add_argument("-p", "--profile",   required=True, help="Path to the test/profile JSON file")
    p.add_argument("-o", "--output-file", default="verification.json", help="Output JSON path")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity (-v, -vv)")
    p.add_argument("--print-diffs", type=int, default=3, metavar="N",
                   help="Print up to N diffs per section on console (default: 3, 0 to disable)")
    p.add_argument("--emit-matches", action="store_true",
                   help="Include matches in output JSON (and enable --print-matches)")
    p.add_argument("--print-matches", type=int, default=0, metavar="N",
                   help="Print up to N matches per section on console (default: 0)")
    p.add_argument("-rep", "--report", action="store_true",
               help="Create an HTML report (results/comparison.html) using report_html.py")

    args = p.parse_args()

    from scrutiny import logging as slog
    slog.setup_logging(args.verbose)

    slog.log_step("Loading schema:", args.schema)
    loader = SchemaLoader(args.schema)
    schema = loader.load()
    slog.log_ok(f"Schema loaded with {len(schema)} section(s).")

    parser = JsonParser(schema)

    slog.log_step("Reading reference JSON:", args.reference)
    data_ref = parser.parse(args.reference)
    slog.log_ok("Reference loaded.")

    slog.log_step("Reading profile JSON:", args.profile)
    data_tst = parser.parse(args.profile)
    slog.log_ok("Profile loaded.")

    results = {"sections": {}}
    order = {"MATCH": 0, "WARN": 1, "SUSPICIOUS": 2}
    worst = "MATCH"

    for section, cfg in schema.items():
        comp_key = (cfg.get("component", {}) or {}).get("comparator", "basic").lower()
        slog.log_step("Comparing section:", f"[{section}] comparator={comp_key}")

        res = compare_schema_section(section, cfg, data_ref, data_tst, emit_matches=args.emit_matches)
        results["sections"][section] = res
        worst = max((worst, res["result"]), key=lambda s: order[s])

        mark = {"MATCH": "✓", "WARN": "⚠", "SUSPICIOUS": "✖"}[res["result"]]
        color_map = {"MATCH": "green", "WARN": "yellow", "SUSPICIOUS": "red"}

        disp = res.get("stats_display") or res.get("stats") or {}
        statline = f"{mark} {section}: {res['result']}  (diffs: {disp.get('changed',0)}/{disp.get('compared',0)})"
        slog.log_info(slog.c(statline, color_map[res["result"]]))

        to_print = min(args.print_diffs, len(res["diffs"])) if args.print_diffs and res["diffs"] else 0
        for i in range(to_print):
            d = res["diffs"][i]
            line = f"    • {d.get('key','')}.{d.get('field','')}: {d.get('ref','')} {d.get('op','!=')} {d.get('test','')}"
            slog.log_info(slog.c(line, "gray"))

        if ("matches" in res) and (args.print_matches):
            mprint = min(args.print_matches, len(res["matches"]))
            for i in range(mprint):
                m = res["matches"][i]
                line = f"    = {m.get('key','')}.{m.get('field','')}: {m.get('value','')}"
                slog.log_info(slog.c(line, "gray"))

    results["overall"] = worst
    results["reference_name"] = "reference"
    results["profile_name"]   = "profile"

    slog.log_info("")
    overall_color = {"MATCH": "green", "WARN": "yellow", "SUSPICIOUS": "red"}[worst]
    slog.log_info(slog.c(f"Overall result: {worst}", overall_color))

    slog.log_step("Writing output JSON:", args.output_file)
    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    if args.report:
        slog.log_ok("Generating HTML report")
        report_script = os.path.join(os.path.dirname(__file__), "report_html.py")
        if not os.path.exists(report_script):
            report_script = "report_html.py"

        try:
            subprocess.run(
                [sys.executable, report_script, "-v", args.output_file, "-o", "comparison.html"],
                check=True
            )
            slog.log_ok("HTML report written to results/comparison.html")
        except subprocess.CalledProcessError as e:
            slog.log_err(f"Failed to build HTML report: {e}")
        except Exception as e:
            slog.log_err(f"Error while generating HTML report: {e}")
    else:
        slog.log_info("Report generation skipped (use -rep/--report to enable).")

    slog.log_ok("Done.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        from scrutiny import logging as slog
        slog.log_err(f"Error: {e}")
        sys.exit(1)
