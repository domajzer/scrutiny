from __future__ import annotations
from typing import Any, Dict, List, Tuple, Iterable
from collections import defaultdict

DiffTuple  = Tuple[str, str, Any, str, Any]   # (key, field, ref, op, test)
MatchTuple = Tuple[str, str, Any]             # (key, field, value)

class BasicComparator:
    """
    Comparator with category awareness + automatic *set mode*.

    • If a section has >1 row per match_key (either side), we switch to *set mode*:
        - group by match_key
        - compare sets of NON-key field tuples per key
        - emit "__group__" diffs for missing/extra tuples
        - counting is user-friendly: one change per key: changed += max(missing, extra); compared += 1
        - when the grouped key MATCHES, we emit a match summary payload instead of None
    • Otherwise we do classic field-by-field comparison (ordinal/continuous/nominal).

    Returns BOTH:
      counts        → field-level stats (kept for compatibility)
      counts_items  → item-level stats (per key) for nicer CLI/HTML summaries
      labels        → {section: {str(key): friendly_label}} using metadata['show_key'] if present
    """

    # ---------- helpers ----------

    @staticmethod
    def _norm_field_def(fdef: Any) -> Dict[str, Any]:
        if isinstance(fdef, str):
            return {"type": fdef, "category": "nominal"}
        if isinstance(fdef, dict):
            out = {"category": "nominal"}
            out.update(fdef)
            return out
        return {"type": "string", "category": "nominal"}

    @staticmethod
    def _num(val: Any):
        try:
            return True, float(val)
        except Exception:
            return False, None

    @staticmethod
    def _num_op(rv: float, tv: float) -> str:
        if rv == tv:
            return "=="
        return "<" if rv < tv else ">"

    @staticmethod
    def _group_by_key(items: Iterable[Dict[str, Any]], key_field: str) -> Dict[Any, List[Dict[str, Any]]]:
        out: Dict[Any, List[Dict[str, Any]]] = {}
        for e in items or []:
            if not isinstance(e, dict):
                continue
            k = e.get(key_field)
            if k is None:
                continue
            out.setdefault(k, []).append(e)
        return out

    @staticmethod
    def _has_duplicates(groups: Dict[Any, List[Dict[str, Any]]]) -> bool:
        return any(len(rows) > 1 for rows in groups.values())

    @staticmethod
    def _signature_from_row(row: Dict[str, Any], key_field: str) -> Tuple[Tuple[str, Any], ...]:
        # include ALL non-key fields; stable order
        return tuple(sorted([(f, v) for f, v in row.items() if f != key_field], key=lambda x: x[0]))

    @staticmethod
    def _summarize_group(rows: List[Dict[str, Any]], key_field: str) -> Dict[str, Any]:
        """Return a compact dict of field -> (single value or sorted list of unique values)."""
        agg = defaultdict(set)
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            for f, v in r.items():
                if f == key_field:
                    continue
                agg[f].add(v)
        summary: Dict[str, Any] = {}
        for f, s in agg.items():
            if len(s) == 1:
                summary[f] = next(iter(s))
            else:
                summary[f] = sorted(s, key=lambda x: (str(type(x)), str(x)))
        return summary

    # ---------- public API ----------

    def __init__(self, schema: Dict[str, Dict[str, Any]],
                       reference: Dict[str, Any],
                       tested: Dict[str, Any]) -> None:
        self.schema   = schema or {}
        self.ref_data = reference or {}
        self.tst_data = tested or {}

    def compare(self, key_field: str = "name", metadata: Dict[str, Any] | None = None) -> Dict[str, List[DiffTuple]]:
        detailed = self.compare_detailed(key_field=key_field, metadata=metadata, return_matches=False)
        return detailed["diffs"]

    def compare_detailed(
        self,
        key_field: str = "name",
        metadata: Dict[str, Any] | None = None,
        *,
        return_matches: bool = False
    ) -> Dict[str, Any]:
        diffs: Dict[str, List[DiffTuple]] = {}
        matches: Dict[str, List[MatchTuple]] = {} if return_matches else {}
        counts: Dict[str, Dict[str, int]] = {}
        counts_items: Dict[str, Dict[str, int]] = {}
        labels_out: Dict[str, Dict[str, str]] = {}

        for section, cfg in self.schema.items():
            fields_raw = cfg.get("fields") or cfg.get("item_fields") or {}
            fields = {fname: self._norm_field_def(fdef) for fname, fdef in fields_raw.items()}

            meta = (cfg.get("metadata") or {}) if metadata is None else (metadata or {})
            # global relative numeric tolerance if in [0,1]
            rel_tol_global = meta.get("threshold_ratio", None)
            try:
                rel_tol_global = float(rel_tol_global)
                if not (0.0 <= rel_tol_global <= 1.0):
                    rel_tol_global = None
            except Exception:
                rel_tol_global = None

            global_ordinal_order: List[Any] = meta.get("ordinal_order", []) or []
            show_key = meta.get("show_key") or key_field

            # Group both sides by key (to auto-detect set-mode)
            ref_groups = self._group_by_key(self.ref_data.get(section, []), key_field)
            tst_groups = self._group_by_key(self.tst_data.get(section, []), key_field)
            auto_set_mode = self._has_duplicates(ref_groups) or self._has_duplicates(tst_groups)

            # Label map (prefer show_key if present)
            key_labels: Dict[str, str] = {}
            def _maybe_label(rows: List[Dict[str, Any]], k: Any) -> None:
                if rows and isinstance(rows[0], dict):
                    lab = rows[0].get(show_key)
                    if lab is not None:
                        key_labels[str(k)] = str(lab)
            for k, rows in ref_groups.items():
                _maybe_label(rows, k)
            for k, rows in tst_groups.items():
                if str(k) not in key_labels:
                    _maybe_label(rows, k)

            if auto_set_mode:
                # ------------------------ SET MODE ------------------------
                section_diffs: List[DiffTuple] = []
                section_matches: List[MatchTuple] = []
                compared = changed = matched = only_ref = only_test = 0

                items_compared = items_changed = items_matched = items_only_ref = items_only_test = 0

                all_keys = sorted(set(ref_groups.keys()) | set(tst_groups.keys()), key=lambda x: (str(type(x)), str(x)))
                for k in all_keys:
                    rlist = ref_groups.get(k)
                    tlist = tst_groups.get(k)

                    if rlist is None or tlist is None:
                        rflag, tflag = rlist is not None, tlist is not None
                        if rflag and not tflag:
                            only_ref += 1; items_only_ref += 1
                            section_diffs.append((str(k), "__presence__", True, "!=", False))
                        elif tflag and not rflag:
                            only_test += 1; items_only_test += 1
                            section_diffs.append((str(k), "__presence__", False, "!=", True))
                        continue

                    Sref = { self._signature_from_row(e, key_field) for e in rlist }
                    Stst = { self._signature_from_row(e, key_field) for e in tlist }

                    if Sref == Stst:
                        matched += 1; items_matched += 1
                        compared += 1; items_compared += 1
                        if return_matches:
                            summary = self._summarize_group(rlist, key_field)
                            # e.g., {"packageName": "javacard.framework", "version": ["1.0","1.1",...]}
                            section_matches.append((str(k), "__group__", summary))
                        continue

                    missing = list(Sref - Stst)
                    extra   = list(Stst - Sref)

                    for tup in missing:
                        section_diffs.append((str(k), "__group__", dict(tup), "!=", None))
                    for tup in extra:
                        section_diffs.append((str(k), "__group__", None, "!=", dict(tup)))

                    changed += max(len(missing), len(extra))
                    compared += 1
                    items_changed += 1; items_compared += 1

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
                labels_out[section] = key_labels
                continue

            # -------------------- FIELD-BY-FIELD MODE --------------------
            ref_items = {e.get(key_field): e for e in self.ref_data.get(section, []) if isinstance(e, dict) and e.get(key_field) is not None}
            tst_items = {e.get(key_field): e for e in self.tst_data.get(section, []) if isinstance(e, dict) and e.get(key_field) is not None}
            keys = sorted(set(ref_items.keys()) | set(tst_items.keys()), key=lambda x: (str(type(x)), str(x)))

            section_diffs: List[DiffTuple] = []
            section_matches: List[MatchTuple] = []
            compared = changed = matched = only_ref = only_test = 0

            items_compared = items_changed = items_matched = items_only_ref = items_only_test = 0

            for k in keys:
                r = ref_items.get(k)
                t = tst_items.get(k)

                if r is None or t is None:
                    rflag, tflag = (r is not None), (t is not None)
                    if rflag and not tflag:
                        only_ref += 1; items_only_ref += 1
                        section_diffs.append((str(k), "__presence__", True, "!=", False))
                    elif tflag and not rflag:
                        only_test += 1; items_only_test += 1
                        section_diffs.append((str(k), "__presence__", False, "!=", True))
                    continue

                key_changed = False
                key_compared_fields = 0

                for fname, fdef in fields.items():
                    if fname == key_field:
                        continue
                    rv = r.get(fname, None)
                    tv = t.get(fname, None)

                    if rv is None and tv is None:
                        matched += 1
                        if return_matches:
                            section_matches.append((str(k), fname, None))
                        key_compared_fields += 1
                        continue
                    if rv is None or tv is None:
                        changed += 1; key_changed = True
                        section_diffs.append((str(k), fname, rv, "!=", tv))
                        key_compared_fields += 1
                        continue

                    if rv == tv:
                        matched += 1
                        if return_matches:
                            section_matches.append((str(k), fname, rv))
                        key_compared_fields += 1
                        continue

                    category = (fdef.get("category") or "nominal").lower()

                    if category == "ordinal":
                        order = fdef.get("order") or global_ordinal_order
                        if order:
                            rank = {v: i for i, v in enumerate(order)}
                            rrank = rank.get(rv); trank = rank.get(tv)
                            if rrank != trank:
                                op = "!=" if (rrank is None or trank is None) else ("<" if rrank < trank else ">")
                                changed += 1; key_changed = True
                                section_diffs.append((str(k), fname, rv, op, tv))
                            else:
                                matched += 1
                                if return_matches:
                                    section_matches.append((str(k), fname, rv))
                        else:
                            changed += 1; key_changed = True
                            section_diffs.append((str(k), fname, rv, "!=" , tv))
                        key_compared_fields += 1
                        continue

                    if category in ("discrete", "continuous"):
                        ok_r, rf = self._num(rv); ok_t, tf = self._num(tv)
                        if ok_r and ok_t:
                            delta = abs(rf - tf)
                            denom = abs(tf) if abs(tf) > 1e-12 else 1.0
                            within_rel = (rel_tol_global is not None) and (delta / denom <= rel_tol_global)
                            if within_rel or rf == tf:
                                matched += 1
                                if return_matches:
                                    section_matches.append((str(k), fname, rf))
                            else:
                                changed += 1; key_changed = True
                                section_diffs.append((str(k), fname, rf, self._num_op(rf, tf), tf))
                            key_compared_fields += 1
                            continue

                        changed += 1; key_changed = True
                        section_diffs.append((str(k), fname, rv, "!=", tv))
                        key_compared_fields += 1
                        continue

                    # nominal
                    changed += 1; key_changed = True
                    section_diffs.append((str(k), fname, rv, "!=", tv))
                    key_compared_fields += 1

                compared += max(0, key_compared_fields)
                if key_compared_fields > 0:
                    items_compared += 1
                    if key_changed:
                        items_changed += 1
                    else:
                        items_matched += 1

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
            labels_out[section] = key_labels

        out = {"diffs": diffs, "counts": counts, "counts_items": counts_items, "labels": labels_out}
        if return_matches:
            out["matches"] = matches
        return out
