# verify.py
import sys
import argparse
import json

from POC.schema_loader import SchemaLoader
from POC.ingest import JsonParser
from POC.comparator_basic import BasicComparator
from POC import logging as slog

# ---- registry of comparators (easy to extend later) ----
COMPARATORS = {
    "basic": BasicComparator,
    # "perf": PerfComparator,
    # "algo-support": AlgSupportComparator,
}

# ---------- Core helpers ----------

def compute_severity(meta: dict, changed: int, compared: int) -> str:
    """
    Decide MATCH / WARN / SUSPICIOUS from counts and metadata thresholds.
    Supports:
      - threshold_ratio (0..1]
      - threshold_count (int)
      - threshold        (<=1 -> ratio, >1 -> count)
    """
    if changed == 0:
        return "MATCH"

    thr_ratio = meta.get("threshold_ratio", None)
    thr_count = meta.get("threshold_count", None)
    thr       = meta.get("threshold", None)

    # Back-compat: interpret "threshold"
    if thr_ratio is None and isinstance(thr, (int, float)) and 0 < thr <= 1:
        thr_ratio = float(thr)
    if thr_count is None and isinstance(thr, (int, float)) and thr > 1:
        thr_count = int(thr)

    if isinstance(thr_ratio, (int, float)) and compared > 0:
        ratio = changed / float(compared)
        return "SUSPICIOUS" if ratio >= float(thr_ratio) else "WARN"

    if isinstance(thr_count, int):
        return "SUSPICIOUS" if changed >= thr_count else "WARN"

    return "WARN"

def compare_schema_section(section: str, cfg: dict, data_ref: dict, data_tst: dict, *, emit_matches: bool) -> dict:
    """
    Run a schema-based comparator for one section and return a result record.
    Includes stats and optionally matches.
    """
    meta       = cfg.get("metadata", {}) or {}
    comp_key   = (meta.get("comparator") or "basic").lower()
    key_field  = meta.get("key_field", "name")
    want_match = emit_matches or bool(meta.get("include_matches", False))

    Comparator = COMPARATORS.get(comp_key, BasicComparator)
    comp = Comparator(
        schema={section: cfg},
        reference={section: data_ref.get(section, [])},
        tested={section: data_tst.get(section, [])},
    )

    detailed = comp.compare_detailed(key_field=key_field, metadata=meta, return_matches=want_match)

    diffs   = detailed["diffs"].get(section, [])
    matches = detailed.get("matches", {}).get(section, []) if want_match else []
    counts  = detailed["counts"].get(section, {"compared": 0, "changed": 0, "matched": 0, "only_ref": 0, "only_test": 0})

    result = compute_severity(meta, changed=counts["changed"], compared=counts["compared"])

    diffs_struct = [
        {"key": n, "field": f, "ref": rv, "op": op, "test": tv}
        for (n, f, rv, op, tv) in diffs
    ]
    matches_struct = [
        {"key": n, "field": f, "value": v}
        for (n, f, v) in matches
    ] if want_match else []

    return {
        "backend": "schema",
        "comparator": comp_key,
        "result": result,
        "stats": {
            "diff_count": len(diffs),
            "compared": counts["compared"],
            "changed": counts["changed"],
            "matched": counts["matched"],
            "only_ref": counts["only_ref"],
            "only_test": counts["only_test"],
        },
        "diffs": diffs_struct,
        **({"matches": matches_struct} if want_match else {}),
    }

# ---------- CLI ----------

def main():
    p = argparse.ArgumentParser(description="YAML-driven verification (schema-first, modular).")
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
    args = p.parse_args()

    slog.setup_logging(args.verbose)

    # 1) Load schema and data
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

    # 2) Per-section dispatch
    results = {"sections": {}}
    order = {"MATCH": 0, "WARN": 1, "SUSPICIOUS": 2}
    worst = "MATCH"

    for section, cfg in schema.items():
        meta = (cfg.get("metadata") or {})
        comp_key = (meta.get("comparator") or "basic").lower()

        slog.log_step("Comparing section:", f"[{section}] comparator={comp_key}")

        res = compare_schema_section(section, cfg, data_ref, data_tst, emit_matches=args.emit_matches)
        results["sections"][section] = res
        worst = max((worst, res["result"]), key=lambda s: order[s])

        # Per-section console outcome
        mark = {"MATCH": "✓", "WARN": "⚠", "SUSPICIOUS": "✖"}[res["result"]]
        color_map = {"MATCH": "green", "WARN": "yellow", "SUSPICIOUS": "red"}
        statline = f"{mark} {section}: {res['result']}  (diffs: {res['stats']['changed']}/{res['stats']['compared']})"
        slog.log_info(slog.c(statline, color_map[res["result"]]))

        # Preview diffs
        to_print = min(args.print_diffs, len(res["diffs"])) if args.print_diffs and res["diffs"] else 0
        for i in range(to_print):
            d = res["diffs"][i]
            line = f"    • {d.get('key','')}.{d.get('field','')}: {d.get('ref','')} {d.get('op','!=')} {d.get('test','')}"
            slog.log_info(slog.c(line, "gray"))

        # Preview matches (if present)
        if args.emit_matches and "matches" in res and args.print_matches:
            mprint = min(args.print_matches, len(res["matches"]))
            for i in range(mprint):
                m = res["matches"][i]
                line = f"    = {m.get('key','')}.{m.get('field','')}: {m.get('value','')}"
                slog.log_info(slog.c(line, "gray"))

    results["overall"] = worst
    results["reference_name"] = "reference"
    results["profile_name"]   = "profile"

    # Summary
    slog.log_info("")
    overall_color = {"MATCH": "green", "WARN": "yellow", "SUSPICIOUS": "red"}[worst]
    slog.log_info(slog.c(f"Overall result: {worst}", overall_color))

    # 3) Write machine-readable output
    slog.log_step("Writing output JSON:", args.output_file)
    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    slog.log_ok("Done.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        slog.log_err(f"Error: {e}")
        sys.exit(1)
