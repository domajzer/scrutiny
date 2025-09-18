from __future__ import annotations
import yaml
from typing import Any, Dict, List, Optional
from copy import deepcopy
from scrutiny import logging as slog

_ALLOWED_CATEGORIES = {"ordinal", "nominal", "continuous", "binary", "set"}
_SUPPORTED_SCHEMA_VERSIONS = {"0.1"}

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep-merge dicts with 'explicit null clears default' semantics.
    If override[k] is None, result[k] = None (do not recurse).
    """
    out = deepcopy(base) if base else {}
    for k, v in (override or {}).items():
        if v is None:
            out[k] = None
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

class SchemaLoader:
    """
    Loads a YAML schema with:
      schema_version: "0.1"
      defaults: { data:..., report:..., component:..., target:... }
      sections:
        <name>:
          data: { type: list, record_schema: {...} }
          report: { types: "table,bar" | ["table","bar"] | null }
          component: { comparator, match_key, include_matches?, threshold_ratio?, threshold_count? }
          target: {}
    """

    def __init__(self, yaml_path: str, *, strict: bool = True):
        self.yaml_path = yaml_path
        self.strict = strict

    def _warn_or_raise(self, msg: str, *, fatal: bool = False) -> None:
        if fatal or self.strict:
            slog.log_err(msg)
            raise ValueError(msg)
        else:
            slog.log_warn(msg)

    def _validate_category(self, field_name: str, cat: Optional[str], section: str) -> None:
        if cat and cat not in _ALLOWED_CATEGORIES:
            self._warn_or_raise(
                f"Section '{section}': field '{field_name}' has unknown category '{cat}'. "
                f"Allowed: {sorted(_ALLOWED_CATEGORIES)}",
                fatal=False
            )

    def _normalize_record_schema(self, rec: Dict[str, Any], section: str) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for fname, fdef in (rec or {}).items():
            if isinstance(fdef, str):
                out[fname] = {"dtype": fdef}
            elif isinstance(fdef, dict):
                if "dtype" not in fdef:
                    self._warn_or_raise(f"Section '{section}': field '{fname}' requires 'dtype'.", fatal=True)
                fcopy = dict(fdef)
                self._validate_category(fname, fcopy.get("category"), section)
                out[fname] = fcopy
            else:
                self._warn_or_raise(
                    f"Section '{section}': record_schema for field '{fname}' must be string or map.", fatal=True
                )
        return out

    def _parse_report_types(self, maybe_types: Any, section: str) -> List[str] | None:
        if maybe_types is None:
            return None
        if isinstance(maybe_types, dict):
            maybe_types = maybe_types.get("types", None)
            if maybe_types is None:
                return None
        if isinstance(maybe_types, str):
            return [t.strip().lower() for t in maybe_types.split(",") if t and t.strip()]
        if isinstance(maybe_types, list):
            return [str(t).strip().lower() for t in maybe_types if str(t).strip()]
        self._warn_or_raise(f"Section '{section}': report.types must be string/list/null.", fatal=True)
        return None

    def _normalize_defaults(self, defaults: Dict[str, Any]) -> Dict[str, Any]:
        # Minimal normalization; sections will still validate specifics.
        data = defaults.get("data", {}) or {}
        if data.get("type") and data["type"] != "list":
            self._warn_or_raise("defaults.data.type must be 'list' if provided.", fatal=True)

        report_types = self._parse_report_types(defaults.get("report", {}).get("types", defaults.get("report")), "defaults")
        report = {"types": report_types} if report_types is not None else {"types": None}

        comp = defaults.get("component", {}) or {}
        target = defaults.get("target", {}) or {}

        return {
            "data": {"type": "list", **({} if not data else data)},
            "report": report,
            "component": {
                "comparator": comp.get("comparator"),
                "match_key": comp.get("match_key"),
                "include_matches": bool(comp.get("include_matches", False)),
                "threshold_ratio": comp.get("threshold_ratio"),
                "threshold_count": comp.get("threshold_count"),
            },
            "target": dict(target),
        }

    def load(self) -> Dict[str, Dict[str, Any]]:
        with open(self.yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # --- schema version ---
        version = str(raw.get("schema_version", "")).strip()
        if version not in _SUPPORTED_SCHEMA_VERSIONS:
            self._warn_or_raise(
                f"Unsupported or missing schema_version '{version}'. "
                f"Supported: {sorted(_SUPPORTED_SCHEMA_VERSIONS)}",
                fatal=True
            )

        # --- defaults ---
        defaults_norm = self._normalize_defaults(raw.get("defaults", {}) or {})
        sections_raw = raw.get("sections") or {}
        if not isinstance(sections_raw, dict) or not sections_raw:
            self._warn_or_raise("No sections defined.", fatal=True)

        out: Dict[str, Dict[str, Any]] = {}

        for section_name, section_cfg in sections_raw.items():
            if not isinstance(section_cfg, dict):
                self._warn_or_raise(f"Section '{section_name}' must be a mapping.", fatal=True)

            # merge defaults → section for each bucket
            merged = {}
            for bucket in ("data", "report", "component", "target"):
                merged[bucket] = _deep_merge(defaults_norm.get(bucket, {}), section_cfg.get(bucket, {}))

            # --- normalize data ---
            data_cfg = merged["data"] or {}
            if data_cfg.get("type") != "list":
                self._warn_or_raise(f"Section '{section_name}': data.type must be 'list'.", fatal=True)

            record_schema = data_cfg.get("record_schema", {})
            if not isinstance(record_schema, dict) or not record_schema:
                self._warn_or_raise(f"Section '{section_name}': data.record_schema must be a non-empty map.", fatal=True)
            record_schema_norm = self._normalize_record_schema(record_schema, section_name)

            data = {
                "type": "list",
                "record_schema": record_schema_norm,
            }

            # --- normalize report ---
            report_types = self._parse_report_types(merged["report"].get("types"), section_name)
            report = {"types": report_types} if report_types is not None else {"types": None}

            # --- normalize component ---
            comp_cfg = merged["component"] or {}
            comparator = (comp_cfg.get("comparator") or "").strip().lower()
            if not comparator:
                self._warn_or_raise(f"Section '{section_name}': component.comparator is mandatory.", fatal=True)

            match_key = comp_cfg.get("match_key", None)
            if not match_key:
                self._warn_or_raise(f"Section '{section_name}': component.match_key is mandatory.", fatal=True)

            if match_key not in record_schema_norm:
                self._warn_or_raise(
                    f"Section '{section_name}': component.match_key '{match_key}' must exist in data.record_schema.",
                    fatal=True
                )

            component = {
                "comparator": comparator,
                "match_key": match_key,
                "include_matches": bool(comp_cfg.get("include_matches", False)),
                "threshold_ratio": comp_cfg.get("threshold_ratio", None),
                "threshold_count": comp_cfg.get("threshold_count", None),
            }

            # --- target (free-form, merged) ---
            target = merged["target"] or {}

            out[section_name] = {
                "data": data,
                "report": report,
                "component": component,
                "target": target,
            }

        return out
