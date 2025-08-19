import sys
import argparse
from itertools import chain
import pprint

from schema_loader import SchemaLoader
from ingest import JsonParser
from normalize import detect_qual_vs_quant, infer_scale, can_parse_number
from report_generator import ReportGenerator

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
        # 1) Load schema (now includes 'fields', 'reports', and 'metadata')
        loader     = SchemaLoader(args.schema)
        schema_def = loader.load()

        pprint.pprint(schema_def)

        # 2) Parse JSONs using full schema
        parser    = JsonParser(schema_def)
        data_ref  = parser.parse(args.reference)
        data_tst  = parser.parse(args.tested)

        # 3) Summary
        print("— Summary of sections and data types —")
        for section, cfg in schema_def.items():
            ref_items = data_ref.get(section, [])
            tst_items = data_tst.get(section, [])
            all_vals  = list(chain(
                (item.get('c2','') for item in ref_items),
                (item.get('c2','') for item in tst_items)
            ))
            kind  = detect_qual_vs_quant(all_vals)
            scale = 'n/a'
            if kind == 'quantitative':
                nums  = [float(v) for v in all_vals if can_parse_number(v)]
                scale = infer_scale(nums)
            print(
                f"  • {section!r}: "
                f"ref={len(ref_items)}, "
                f"tst={len(tst_items)}, "
                f"{kind}{f' ({scale})' if scale!='n/a' else ''}"
            )

        # 4) Generate HTML report (if requested)
        if args.html_report:
            rg = ReportGenerator(schema_def, data_ref, data_tst)
            rg.create(args.html_report)
            print(f"📄 HTML report written to '{args.html_report}'")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
