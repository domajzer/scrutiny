# scrutiny/javacard/modules/algperf_comparator.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple

DiffTuple  = Tuple[str, str, Any, str, Any]   # (key, field, ref, op, test)
MatchTuple = Tuple[str, str, Any]             # (key, field, value)

class AlgPerfComparator:
    """
    Comparator specialized for JCAlgTest-like algorithm performance entries.

    Comparison rules (drawn from the old AlgPerformance logic):
      • If algorithm is present only on one side -> __presence__ diff.
      • If error flags differ -> diff on 'error'.
      • If both errored (same message) -> match on 'error'.
      • If both succeeded:
          - If both avg <= 2 ms -> treat as 'skipped' match (noise floor).
          - Else compute avg_diff = |ref.avg - tst.avg|.
            If (avg_diff > (ref.max - ref.min)) AND (avg_diff > 0.2 * ref.avg):
                - If both avg <= 10 ms OR key contains "clearKey()" -> mark as 'skipped' match.
                - Else diff on 'avg_ms'.
            Else -> match on 'avg_ms'.

    Output adds a lightweight 'chart' payload for HTML rendering (rows with ref/test avg, delta, delta% and status).
    """

    KEY_AVG = "avg_ms"
    KEY_MIN = "min_ms"
    KEY_MAX = "max_ms"
    KEY_ERR = "error"

    def __init__(self, schema: Dict[str, Dict[str, Any]],
                       reference: Dict[str, Any],
                       tested: Dict[str, Any]) -> None:
        self.schema   = schema or {}
        self.ref_data = reference or {}
        self.tst_data = tested or {}

    @staticmethod
    def _num(val: Any) -> float | None:
        try:
            return float(val)
        except Exception:
            return None

    @staticmethod
    def _op(rv: float, tv: float) -> str:
        if rv == tv: return "=="
        return "<" if rv < tv else ">"

    def compare_detailed(
        self,
        key_field: str = "algorithm",
        metadata: Dict[str, Any] | None = None,
        *,
        return_matches: bool = False
    ) -> Dict[str, Any]:
        diffs: Dict[str, List[DiffTuple]] = {}
        matches: Dict[str, List[MatchTuple]] = {} if return_matches else {}
        counts: Dict[str, Dict[str, int]] = {}
        counts_items: Dict[str, Dict[str, int]] = {}
        labels_out: Dict[str, Dict[str, str]] = {}
        chart_out: Dict[str, List[Dict[str, Any]]] = {}

        for section, cfg in self.schema.items():
            ref_rows = [e for e in self.ref_data.get(section, []) if isinstance(e, dict)]
            tst_rows = [e for e in self.tst_data.get(section, []) if isinstance(e, dict)]

            ref_map = {r.get(key_field): r for r in ref_rows if r.get(key_field) is not None}
            tst_map = {r.get(key_field): r for r in tst_rows if r.get(key_field) is not None}
            keys = sorted(set(ref_map.keys()) | set(tst_map.keys()), key=lambda x: (str(type(x)), str(x)))

            section_diffs: List[DiffTuple] = []
            section_matches: List[MatchTuple] = []
            chart_rows: List[Dict[str, Any]] = []

            compared = changed = matched = only_ref = only_test = 0
            items_compared = items_changed = items_matched = items_only_ref = items_only_test = 0

            for k in keys:
                r = ref_map.get(k)
                t = tst_map.get(k)

                if r is None or t is None:
                    if r is not None and t is None:
                        only_ref += 1; items_only_ref += 1
                        section_diffs.append((str(k), "__presence__", True, "!=", False))
                        chart_rows.append({
                            "key": str(k), "status": "missing", "ref_avg": self._num(r.get(self.KEY_AVG)) if r else None,
                            "test_avg": None, "delta_ms": None, "delta_pct": None, "note": "present only in reference"
                        })
                    elif t is not None and r is None:
                        only_test += 1; items_only_test += 1
                        section_diffs.append((str(k), "__presence__", False, "!=", True))
                        chart_rows.append({
                            "key": str(k), "status": "extra", "ref_avg": None,
                            "test_avg": self._num(t.get(self.KEY_AVG)) if t else None, "delta_ms": None, "delta_pct": None,
                            "note": "present only in profile"
                        })
                    continue

                meta = (cfg.get("metadata") or {}) if metadata is None else (metadata or {})
                show_key = meta.get("show_key") or key_field
                label_map = labels_out.setdefault(section, {})
                if str(k) not in label_map:
                    lab = r.get(show_key, r.get(key_field, k))
                    label_map[str(k)] = str(lab)

                r_err = r.get(self.KEY_ERR, None)
                t_err = t.get(self.KEY_ERR, None)

                if r_err != t_err:
                    changed += 1; items_changed += 1; items_compared += 1
                    section_diffs.append((str(k), self.KEY_ERR, r_err, "!=", t_err))
                    chart_rows.append({
                        "key": str(k), "status": "error_mismatch", "ref_avg": None, "test_avg": None,
                        "delta_ms": None, "delta_pct": None, "note": f"error ref={r_err} vs prof={t_err}"
                    })
                    continue

                if r_err is not None and t_err is not None:
                    matched += 1; items_matched += 1; items_compared += 1
                    if return_matches:
                        section_matches.append((str(k), self.KEY_ERR, r_err))
                    chart_rows.append({
                        "key": str(k), "status": "error", "ref_avg": None, "test_avg": None,
                        "delta_ms": None, "delta_pct": None, "note": f"both failed: {r_err}"
                    })
                    continue

                r_avg = self._num(r.get(self.KEY_AVG))
                t_avg = self._num(t.get(self.KEY_AVG))
                r_min = self._num(r.get(self.KEY_MIN))
                r_max = self._num(r.get(self.KEY_MAX))

                if r_avg is None or t_avg is None:
                    changed += 1; items_changed += 1; items_compared += 1
                    section_diffs.append((str(k), self.KEY_AVG, r.get(self.KEY_AVG), "!=", t.get(self.KEY_AVG)))
                    chart_rows.append({
                        "key": str(k), "status": "data_error", "ref_avg": r_avg, "test_avg": t_avg,
                        "delta_ms": None, "delta_pct": None, "note": "missing numeric avg"
                    })
                    continue

                if r_avg <= 2.0 and t_avg <= 2.0:
                    matched += 1; items_matched += 1; items_compared += 1
                    if return_matches:
                        section_matches.append((str(k), f"{self.KEY_AVG} (skipped)", t_avg))
                    chart_rows.append({
                        "key": str(k), "status": "skipped", "ref_avg": r_avg, "test_avg": t_avg,
                        "delta_ms": t_avg - r_avg, "delta_pct": (t_avg - r_avg) / r_avg * 100.0 if r_avg else None,
                        "note": "both ≤ 2 ms"
                    })
                    continue

                avg_diff = abs(r_avg - t_avg)
                ref_spread = (r_max - r_min) if (r_max is not None and r_min is not None) else 0.0
                significant = (avg_diff > ref_spread) and (avg_diff > 0.2 * r_avg)

                is_clearkey = ("clearKey()" in str(k))

                if significant and not ((r_avg <= 10.0 and t_avg <= 10.0) or is_clearkey):
                    changed += 1; items_changed += 1; items_compared += 1
                    section_diffs.append((str(k), self.KEY_AVG, r_avg, self._op(r_avg, t_avg), t_avg))
                    chart_rows.append({
                        "key": str(k), "status": "mismatch", "ref_avg": r_avg, "test_avg": t_avg,
                        "delta_ms": t_avg - r_avg, "delta_pct": (t_avg - r_avg) / r_avg * 100.0 if r_avg else None,
                        "note": "significant diff"
                    })
                else:
                    matched += 1; items_matched += 1; items_compared += 1
                    field_name = self.KEY_AVG if not (r_avg <= 10.0 and t_avg <= 10.0 or is_clearkey) else f"{self.KEY_AVG} (skipped)"
                    if return_matches:
                        section_matches.append((str(k), field_name, t_avg))
                    chart_rows.append({
                        "key": str(k), "status": "match" if field_name == self.KEY_AVG else "skipped",
                        "ref_avg": r_avg, "test_avg": t_avg,
                        "delta_ms": t_avg - r_avg, "delta_pct": (t_avg - r_avg) / r_avg * 100.0 if r_avg else None,
                        "note": "similar" if field_name == self.KEY_AVG else "fast op"
                    })

            diffs[section] = section_diffs
            if return_matches:
                matches[section] = section_matches

            counts[section] = {
                "compared": compared, "changed": changed, "matched": matched,
                "only_ref": only_ref, "only_test": only_test,
            }
            counts_items[section] = {
                "compared": items_compared, "changed": items_changed, "matched": items_matched,
                "only_ref": items_only_ref, "only_test": items_only_test,
            }
            chart_out[section] = chart_rows

        out = {"diffs": diffs, "counts": counts, "counts_items": counts_items, "labels": labels_out, "chart": chart_out}
        if return_matches:
            out["matches"] = matches
        return out
