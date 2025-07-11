import sys
import argparse
from itertools import chain

from schema_loader import SchemaLoader
from normalize import detect_qual_vs_quant, infer_scale, can_parse_number
from ingest import JsonParser
from compare import JsonComparator
from visualization import generate_html_report

if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Validate two JSON files against a YAML schema, normalize & compare"
    )
    p.add_argument("-s", "--schema",    required=True, help="Path to structure.yml")
    p.add_argument("-r", "--reference", required=True, help="Path to the reference JSON file")
    p.add_argument("-t", "--tested",    required=True, help="Path to the tested JSON file")
    p.add_argument("--html-report", help="If provided, path to write an HTML report")
    args = p.parse_args()

    try:
        # 1) Load schema
        loader = SchemaLoader(args.schema)
        schema = loader.load()
        print(f"✅ Parsed schema '{args.schema}'")

        # 2) Parse JSONs
        parser = JsonParser(schema)
        data_ref = parser.parse(args.reference)
        print(f"✅ Parsed reference '{args.reference}'")
        data_tst = parser.parse(args.tested)
        print(f"✅ Parsed tested    '{args.tested}'\n")

        # 3) Normalize & report counts + measurement type
        print("— Summary of sections and data types —")
        for section in schema:
            ref_items = data_ref.get(section, [])
            tst_items = data_tst.get(section, [])
            
            all_vals = list(chain((item.get('c2','') for item in ref_items),(item.get('c2','') for item in tst_items)))

            kind = detect_qual_vs_quant(all_vals)
            scale = 'n/a'
            if kind == 'quantitative':
                nums = [float(v) for v in all_vals if can_parse_number(v)]
                scale = infer_scale(nums)

            print(f"  • {section!r}: ref={len(ref_items)}, tst={len(tst_items)}, {kind}{f' ({scale})' if scale!='n/a' else ''}")

        # 4) Compare
        comparator = JsonComparator(data_ref, data_tst)
        diffs = comparator.compare()

        # 5) Print detailed diff report
        print("\n— Detailed Differences —")
        comparator.print_report(diffs)

        # 6) Optionally generate HTML report
        if args.html_report:
            generate_html_report(data_ref, data_tst, diffs, args.html_report)
            print(f"📄 HTML report written to '{args.html_report}'")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
