# POC/comparator_basic.py

from __future__ import annotations
from typing import Any, Dict, List, Tuple

DiffTuple = Tuple[str, str, Any, str, Any]   # (key, field, ref, op, test)
MatchTuple = Tuple[str, str, Any]            # (key, field, value)

class BasicComparator:
    """
    Schema-driven comparator with category awareness.

    Inputs:
      - schema:   { <section>: { 'fields' or 'item_fields': {...}, 'metadata': {...} } }
      - reference/tested: { <section>: [ {field: value, ...}, ... ] }

    compare(key_field, metadata) -> { section: [DiffTuple, ...] }
    compare_detailed(...) -> {
        "diffs":   { section: [DiffTuple, ...] },
        "matches": { section: [MatchTuple, ...] },   # if return_matches=True
        "counts":  { section: {"compared":N,"changed":C,"matched":M,"only_ref":A,"only_test":B} }
    }
    """

    def __init__(self, schema: Dict[str, Dict[str, Any]],
                       reference: Dict[str, Any],
                       tested: Dict[str, Any]) -> None:
        self.schema   = schema or {}
        self.ref_data = reference or {}
        self.tst_data = tested or {}

    # ---------- helpers ----------

    @staticmethod
    def _norm_field_def(fdef: Any) -> Dict[str, Any]:
        """Normalize a field def that may be 'string' or a dict."""
        if isinstance(fdef, str):
            return {"type": fdef, "category": "nominal", "required": True}
        if isinstance(fdef, dict):
            out = {"category": "nominal", "required": True}
            out.update(fdef)
            return out
        return {"type": "string", "category": "nominal", "required": True}

    @staticmethod
    def _num(val: Any):
        """Try to convert to float; return (ok, float_val)."""
        try:
            return True, float(val)
        except Exception:
            return False, None

    @staticmethod
    def _num_op(rv: float, tv: float) -> str:
        if rv == tv:
            return "=="
        return "<" if rv < tv else ">"

    def compare(self, key_field: str = "name", metadata: Dict[str, Any] | None = None) -> Dict[str, List[DiffTuple]]:
        """Back-compat: return diffs only."""
        detailed = self.compare_detailed(key_field=key_field, metadata=metadata, return_matches=False)
        return detailed["diffs"]

    def compare_detailed(self, key_field: str = "name", metadata: Dict[str, Any] | None = None, *, return_matches: bool = False) -> Dict[str, Any]:
        diffs: Dict[str, List[DiffTuple]] = {}
        matches: Dict[str, List[MatchTuple]] = {} if return_matches else {}
        counts: Dict[str, Dict[str, int]] = {}

        for section, cfg in self.schema.items():
            fields_raw = cfg.get("fields") or cfg.get("item_fields") or {}
            fields = {fname: self._norm_field_def(fdef) for fname, fdef in fields_raw.items()}

            meta = (cfg.get("metadata") or {}) if metadata is None else (metadata or {})
            tol_map: Dict[str, Dict[str, float]] = meta.get("tolerance", {}) or {}
            global_ordinal_order: List[Any] = meta.get("ordinal_order", []) or []

            ref_items = {e.get(key_field): e for e in self.ref_data.get(section, []) if isinstance(e, dict) and e.get(key_field) is not None}
            tst_items = {e.get(key_field): e for e in self.tst_data.get(section, []) if isinstance(e, dict) and e.get(key_field) is not None}
            keys = sorted(set(ref_items.keys()) | set(tst_items.keys()), key=lambda x: (str(type(x)), str(x)))

            section_diffs: List[DiffTuple] = []
            section_matches: List[MatchTuple] = []
            compared = changed = matched = only_ref = only_test = 0

            for k in keys:
                r = ref_items.get(k)
                t = tst_items.get(k)

                # Presence-only
                if r is None or t is None:
                    rflag, tflag = (r is not None), (t is not None)
                    if rflag and not tflag:
                        only_ref += 1
                        section_diffs.append((str(k), "__presence__", True, "!=", False))
                    elif tflag and not rflag:
                        only_test += 1
                        section_diffs.append((str(k), "__presence__", False, "!=", True))
                    continue

                # Compare each declared field 
                for fname, fdef in fields.items():
                    if fname == key_field:
                        continue
                    rv = r.get(fname, None)
                    tv = t.get(fname, None)

                    # Treat both None as equal; one None -> diff
                    if rv is None and tv is None:
                        # consider matched (present field, equal None)
                        matched += 1
                        if return_matches:
                            section_matches.append((str(k), fname, None))
                        continue
                    if rv is None or tv is None:
                        changed += 1
                        section_diffs.append((str(k), fname, rv, "!=", tv))
                        continue

                    if rv == tv:
                        matched += 1
                        if return_matches:
                            section_matches.append((str(k), fname, rv))
                        continue

                    category = (fdef.get("category") or "nominal").lower()

                    if category == "ordinal":
                        order = fdef.get("order") or global_ordinal_order
                        if order:
                            rank = {v: i for i, v in enumerate(order)}
                            rrank = rank.get(rv, None)
                            trank = rank.get(tv, None)
                            if rrank != trank:
                                op = "!=" if (rrank is None or trank is None) else ("<" if rrank < trank else ">")
                                changed += 1
                                section_diffs.append((str(k), fname, rv, op, tv))
                            else:
                                matched += 1
                                if return_matches:
                                    section_matches.append((str(k), fname, rv))
                        else:
                            # fall back to nominal
                            changed += 1
                            section_diffs.append((str(k), fname, rv, "!=", tv))
                        continue

                    if category in ("discrete", "continuous"):
                        ok_r, rf = self._num(rv)
                        ok_t, tf = self._num(tv)
                        if ok_r and ok_t:
                            tol = tol_map.get(fname, {}) or {}
                            abs_tol = tol.get("abs", None)
                            rel_tol = tol.get("rel", None)
                            delta = abs(rf - tf)
                            within_abs = isinstance(abs_tol, (int, float)) and delta <= float(abs_tol)
                            within_rel = isinstance(rel_tol, (int, float)) and (abs(tf) > 0) and (delta / abs(tf) <= float(rel_tol))
                            if within_abs or within_rel or rf == tf:
                                matched += 1
                                if return_matches:
                                    section_matches.append((str(k), fname, rf))
                            else:
                                changed += 1
                                section_diffs.append((str(k), fname, rf, self._num_op(rf, tf), tf))
                            continue
                        # numeric parse failed -> treat as nominal
                        changed += 1
                        section_diffs.append((str(k), fname, rv, "!=", tv))
                        continue

                    # nominal (default)
                    changed += 1
                    section_diffs.append((str(k), fname, rv, "!=", tv))

                # Count how many fields we actually compared on this row
                compared += max(0, len(fields) - (1 if key_field in fields else 0))

            diffs[section] = section_diffs
            if return_matches:
                matches[section] = section_matches
            counts[section] = {
                "compared": compared,
                "changed": changed,
                "matched": matched,
                "only_ref": only_ref,
                "only_test": only_test,
            }

        out = {"diffs": diffs, "counts": counts}
        if return_matches:
            out["matches"] = matches
        return out
