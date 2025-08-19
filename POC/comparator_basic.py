# comparator_basic.py
class BasicComparator:
    """
    Compare two dicts of parsed entries by numeric or string ops per field,
    driving off the schema.
    """
    def __init__(self, schema: dict, reference: dict[str, list[dict]], tested: dict[str, list[dict]]):
        # schema: { section: { 'fields': {…}, 'reports': […] }, … }
        self.schema = schema
        self.ref    = reference
        self.test   = tested

    def compare(self) -> dict[str, list[tuple]]:
        diffs = {}
        for section, cfg in self.schema.items():
            fields    = cfg['fields']
            ref_list  = self.ref.get(section, [])
            tst_list  = self.test.get(section, [])
            section_diffs: list[tuple] = []

            for ref_entry in ref_list:
                name  = ref_entry.get('name')
                match = next((t for t in tst_list if t.get('name') == name), None)
                if not match:
                    continue

                for field in fields:
                    rv = ref_entry.get(field)
                    tv = match.get(field)
                    if rv is None or tv is None:
                        continue

                    # numeric?
                    try:
                        rf = float(rv)
                        tf = float(tv)
                        if rf == tf:
                            op = '=='
                        elif rf < tf:
                            op = '<='
                        else:
                            op = '>='
                        section_diffs.append((name, field, rf, op, tf))
                    except (ValueError, TypeError):
                        if rv != tv:
                            section_diffs.append((name, field, rv, '!=', tv))

            diffs[section] = section_diffs
        return diffs
 
