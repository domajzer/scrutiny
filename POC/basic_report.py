# basic_report.py

"""
Generate a full‐data HTML report, coloring only the cells where values differ.

Tables per section will have:
  ┌───────┬─────────┬─────────┬─────────┬─────────┐
  │ Name  │ Field A (ref) │ Field A (tst) │ Field B (ref) │ Field B (tst) │
  ├───────┼─────────┼─────────┼─────────┼─────────┤
  │ foo   │ 123     │ 124     │ red     │ red     │
  │ bar   │ 5       │ 5       │ blue    │ green   │
  └───────┴─────────┴─────────┴─────────┴─────────┘
Cells where comparator found a diff get a light‐red background.
"""

def generate_basic_html_report(
    schema: dict[str, dict],
    data_ref: dict[str, list[dict]],
    data_tst: dict[str, list[dict]],
    diffs: dict[str, list[tuple]],
    output_path: str
):
    html = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8">',
        '<title>Full Comparison Report</title>',
        '<style>',
        '  table { border-collapse: collapse; width: 100%; margin-bottom: 2em }',
        '  th, td { border: 1px solid #ccc; padding: 0.5em; }',
        '  th { background: #f2f2f2; }',
        '  .diff { background: #ffdddd; }',
        '</style>',
        '</head><body>',
        '<h1>Full Comparison Report</h1>'
    ]

    for section, cfg in schema.items():
        # only produce a table if 'table' is in the reports list
        if 'table' not in cfg.get('reports', []):
            continue

        fields = list(cfg['fields'].keys())
        # build a quick lookup: diffs_map[name][field] = True
        diffs_map: dict[str, set[str]] = {}
        for name, field, *_ in diffs.get(section, []):
            diffs_map.setdefault(name, set()).add(field)

        html.append(f'<h2>{section}</h2>')
        html.append('<table>')
        # header row
        header_cells = ['<th>Name</th>']
        for f in fields:
            if f == 'name': 
                continue
            header_cells.append(f'<th>{f} (ref)</th><th>{f} (tst)</th>')
        html.append('<tr>' + ''.join(header_cells) + '</tr>')

        # collect all names
        names = {
            *[e['name'] for e in data_ref.get(section, [])],
            *[e['name'] for e in data_tst.get(section, [])]
        }

        for name in sorted(names):
            # find the entries (might be missing on one side)
            ref_ent = next((e for e in data_ref.get(section, []) if e['name']==name), {})
            tst_ent = next((e for e in data_tst.get(section, []) if e['name']==name), {})

            row_cells = [f'<td>{name}</td>']
            for f in fields:
                if f == 'name':
                    continue
                rv = ref_ent.get(f, '')
                tv = tst_ent.get(f, '')
                is_diff = f in diffs_map.get(name, ())
                cls = ' class="diff"' if is_diff else ''
                row_cells.append(f'<td{cls}>{rv}</td><td{cls}>{tv}</td>')
            html.append('<tr>' + ''.join(row_cells) + '</tr>')

        html.append('</table>')

    html.append('</body></html>')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html))
