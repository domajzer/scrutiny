#compare.py

class JsonComparator:
    """
    Compare two parsed JSON-by-schema dictionaries,
    producing per-section and per-entry diffs.
    """
    def __init__(self, reference: dict[str, list[dict]], tested: dict[str, list[dict]]):
        self.ref   = reference
        self.test  = tested

    def compare(self) -> dict:
        """
        Returns a dict of diffs:
          {
            section_name: {
              'added': [ entries in tested but not in ref ],
              'removed': [ entries in ref but not in tested ],
              'changed': [ (ref_entry, test_entry) where entries share same 'name' but differ in other fields ]
            },
            ...
          }
        """
        diffs = {}
        all_sections = sorted(set(self.ref) | set(self.test))
        for section in all_sections:
            ref_items = {e['name']: e for e in self.ref.get(section, [])}
            tst_items = {e['name']: e for e in self.test.get(section, [])}

            added   = [tst_items[n] for n in (set(tst_items) - set(ref_items))]
            removed = [ref_items[n] for n in (set(ref_items) - set(tst_items))]

            changed = []
            for name in set(ref_items) & set(tst_items):
                if ref_items[name] != tst_items[name]:
                    changed.append((ref_items[name], tst_items[name]))

            diffs[section] = {
                'added':   added,
                'removed': removed,
                'changed': changed
            }
        return diffs

    def print_report(self, diffs: dict):
        for section, bucket in diffs.items():
            a, r, c = len(bucket['added']), len(bucket['removed']), len(bucket['changed'])
            print(f"\n=== Section {section!r} — +{a} / -{r} / Δ{c} ===")

            if bucket['added']:
                print("  + Added:")
                for e in bucket['added']:
                    print(f"      {e}")
            if bucket['removed']:
                print("  - Removed:")
                for e in bucket['removed']:
                    print(f"      {e}")
            if bucket['changed']:
                print("  ~ Changed:")
                for before, after in bucket['changed']:
                    print(f"      • {before}  →  {after}")
