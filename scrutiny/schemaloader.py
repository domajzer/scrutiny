from __future__ import annotations
import yaml
from typing import Any, Dict, List, Optional
from copy import deepcopy
from scrutiny import logging as slog

_ALLOWED_CATEGORIES = {"ordinal", "nominal", "continuous", "binary", "set"}
_SUPPORTED_SCHEMA_VERSIONS = {"0.1", "0.11", "0.12"}

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
      schema_version: "0.1" | "0.11" | "0.12"
      defaults: { data:..., report:..., component:..., target:... }
      sections:
        <name>:
          data: { type: list, record_schema: {...} }
          report: { types: "table,bar" | ["table","bar"] | null, theme: light|dark }
          component: { comparator, match_key, show_key?, include_matches?, threshold_ratio?, threshold_count? }
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
                    f"Section '{section}': record_schema for field '{fname}' must be string or map.",
                    fatal=True
                )
        return out

    def _parse_report_types(self, maybe_types: Any, section: str) -> List[str] | None:
        """
        Accept:
          - null -> None
          - "table,radar" -> ["table","radar"]
          - ["table","radar"] -> ["table","radar"]
          - {"types": ...} -> parsed types
        """
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

    def _parse_theme(self, report_raw: Any, section: str) -> Optional[str]:
        """
        Accept theme only as a key inside a report mapping:
          report: { theme: dark }
        Returns "light"|"dark"|None.
        """
        if not isinstance(report_raw, dict):
            return None
        t = report_raw.get("theme", None)
        if t is None:
            return None
        tt = str(t).strip().lower()
        if tt not in {"light", "dark"}:
            self._warn_or_raise(f"Section '{section}': report.theme must be 'light' or 'dark' if provided.", fatal=True)
        return tt

    def _normalize_defaults(self, defaults: Dict[str, Any]) -> Dict[str, Any]:
        data = defaults.get("data", {}) or {}
        if data.get("type") and data["type"] != "list":
            self._warn_or_raise("defaults.data.type must be 'list' if provided.", fatal=True)

        report_raw = defaults.get("report", {}) or {}
        report_types = self._parse_report_types(
            report_raw.get("types", report_raw) if isinstance(report_raw, dict) else report_raw,
            "defaults"
        )
        theme = self._parse_theme(report_raw, "defaults")

        report = {
            "types": report_types if report_types is not None else None,
            "theme": theme,
        }

        comp = defaults.get("component", {}) or {}
        target = defaults.get("target", {}) or {}

        return {
            "data": {"type": "list", **({} if not data else data)},
            "report": report,
            "component": {
                "comparator": comp.get("comparator"),
                "match_key": comp.get("match_key"),
                "show_key": comp.get("show_key"),  # optional
                "include_matches": bool(comp.get("include_matches", False)),
                "threshold_ratio": comp.get("threshold_ratio"),
                "threshold_count": comp.get("threshold_count"),
            },
            "target": dict(target),
        }

    def load(self) -> Dict[str, Dict[str, Any]]:
        with open(self.yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        version = str(raw.get("schema_version", "")).strip()
        if version not in _SUPPORTED_SCHEMA_VERSIONS:
            self._warn_or_raise(
                f"Unsupported or missing schema_version '{version}'. "
                f"Supported: {sorted(_SUPPORTED_SCHEMA_VERSIONS)}",
                fatal=True
            )

        defaults_norm = self._normalize_defaults(raw.get("defaults", {}) or {})
        sections_raw = raw.get("sections") or {}
        if not isinstance(sections_raw, dict) or not sections_raw:
            self._warn_or_raise("No sections defined.", fatal=True)

        out: Dict[str, Dict[str, Any]] = {}

        for section_name, section_cfg in sections_raw.items():
            if not isinstance(section_cfg, dict):
                self._warn_or_raise(f"Section '{section_name}' must be a mapping.", fatal=True)

            merged: Dict[str, Any] = {}
            for bucket in ("data", "report", "component", "target"):
                merged[bucket] = _deep_merge(defaults_norm.get(bucket, {}), section_cfg.get(bucket, {}))

            # --- data ---
            data_cfg = merged["data"] or {}
            if data_cfg.get("type") != "list":
                self._warn_or_raise(f"Section '{section_name}': data.type must be 'list'.", fatal=True)

            record_schema = data_cfg.get("record_schema", {})
            if not isinstance(record_schema, dict) or not record_schema:
                self._warn_or_raise(f"Section '{section_name}': data.record_schema must be a non-empty map.", fatal=True)
            record_schema_norm = self._normalize_record_schema(record_schema, section_name)

            data = {"type": "list", "record_schema": record_schema_norm}

            # --- report ---
            report_cfg = merged.get("report") or {}
            report_types = self._parse_report_types(report_cfg.get("types", None), section_name)
            theme = self._parse_theme(report_cfg, section_name)
            report = {
                "types": report_types if report_types is not None else None,
                "theme": theme,
            }

            # --- component ---
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

            show_key = comp_cfg.get("show_key", None)
            if show_key is not None and show_key not in record_schema_norm:
                self._warn_or_raise(
                    f"Section '{section_name}': component.show_key '{show_key}' not in data.record_schema; "
                    f"falling back to match_key '{match_key}'.",
                    fatal=False
                )
                show_key = None

            component = {
                "comparator": comparator,
                "match_key": match_key,
                "show_key": show_key,  # may be None; runtime fallback to match_key
                "include_matches": bool(comp_cfg.get("include_matches", False)),
                "threshold_ratio": comp_cfg.get("threshold_ratio", None),
                "threshold_count": comp_cfg.get("threshold_count", None),
            }

            target = merged["target"] or {}

            out[section_name] = {
                "data": data,
                "report": report,
                "component": component,
                "target": target,
            }

        return out
