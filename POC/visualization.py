def generate_html_report(data_ref, data_tst, diffs, output_path):
    """
    Generate a basic HTML report showing side-by-side tables for each section,
    with changed cells highlighted.
    :param data_ref: dict of reference data {section: [entry_dicts]}
    :param data_tst: dict of tested data {section: [entry_dicts]}
    :param diffs: dict of diffs from JsonComparator.compare()
    :param output_path: file path to write the HTML report
    """
    # Start HTML
    html_lines = [
        '<!DOCTYPE html>',
        '<html>',
        '<head>',
        '  <meta charset="utf-8">',
        '  <title>Scrutiny Comparison Report</title>',
        '  <style>',
        '    table { border-collapse: collapse; width: 100%; margin-bottom: 2em; }',
        '    th, td { border: 1px solid #ccc; padding: 0.5em; }',
        '    th { background-color: #f2f2f2; }',
        '    .changed { background-color: #ffdddd; }',
        '    h2 { margin-top: 1.5em; }',
        '  </style>',
        '</head>',
        '<body>',
        '  <h1>Scrutiny Comparison Report</h1>'
    ]

    sections = sorted(set(data_ref) | set(data_tst))
    for section in sections:
        ref_entries = data_ref.get(section, [])
        tst_entries = data_tst.get(section, [])
        section_diff = diffs.get(section, {})
        # Build map of changed entries by name
        changed_map = {before['name']: (before, after)
                       for before, after in section_diff.get('changed', [])}

        # Reference table
        html_lines.append(f'  <h2>{section} (Reference) - {len(ref_entries)} items</h2>')
        if ref_entries:
            keys = list(ref_entries[0].keys())
            html_lines.append('  <table>')
            html_lines.append('    <tr>' + ''.join(f'<th>{k}</th>' for k in keys) + '</tr>')
            for entry in ref_entries:
                name = entry.get('name')
                html_lines.append('    <tr>')
                for k in keys:
                    cell = entry.get(k, '')
                    cls = ''
                    if name in changed_map:
                        before, after = changed_map[name]
                        if before.get(k) != after.get(k):
                            cls = ' class="changed"'
                    html_lines.append(f'      <td{cls}>{cell}</td>')
                html_lines.append('    </tr>')
            html_lines.append('  </table>')
        else:
            html_lines.append('  <p>No reference entries</p>')

        # Tested table
        html_lines.append(f'  <h2>{section} (Tested) - {len(tst_entries)} items</h2>')
        if tst_entries:
            keys = list(tst_entries[0].keys())
            html_lines.append('  <table>')
            html_lines.append('    <tr>' + ''.join(f'<th>{k}</th>' for k in keys) + '</tr>')
            for entry in tst_entries:
                name = entry.get('name')
                html_lines.append('    <tr>')
                for k in keys:
                    cell = entry.get(k, '')
                    cls = ''
                    if name in changed_map:
                        before, after = changed_map[name]
                        if before.get(k) != after.get(k):
                            cls = ' class="changed"'
                    html_lines.append(f'      <td{cls}>{cell}</td>')
                html_lines.append('    </tr>')
            html_lines.append('  </table>')
        else:
            html_lines.append('  <p>No tested entries</p>')

    # End HTML
    html_lines.extend(['</body>', '</html>'])

    # Write file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(html_lines))
