# schema_loader.py

import yaml

class SchemaLoader:
    """
    Loads a YAML file of the form:

    sections:
      SectionName:
        type: list
        item_fields:
          field1: string
          field2:
            type: number
            category: continuous
        report: "table,bar"   # MANDATORY: comma-delimited string or null
        threshold: 0.05       # ← will end up in metadata
        ci_alpha: 0.01        # ← will end up in metadata
      ...
    """

    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path

    def load(self) -> dict[str, dict]:
        with open(self.yaml_path, 'r') as f:
            raw = yaml.safe_load(f)

        schema: dict[str, dict] = {}
        for section_name, cfg in raw.get('sections', {}).items():
            # --- 1) Core validation ---
            if cfg.get('type') != 'list':
                raise ValueError(f"Section '{section_name}' must be declared as a list")

            fields = cfg.get('item_fields')
            if not isinstance(fields, dict):
                raise ValueError(f"'item_fields' for section '{section_name}' must be a dict")

            # --- 2) Enforce mandatory 'report' key ---
            if 'report' not in cfg:
                raise KeyError(f"Section '{section_name}' is missing required 'report' key")
            report_spec = cfg['report']
            if report_spec is None:
                # user explicitly says “no report”
                reports = None
            elif isinstance(report_spec, str):
                # parse comma-delimited list
                reports = [r.strip() for r in report_spec.split(',') if r.strip()]
            else:
                raise ValueError(
                    f"'report' for section '{section_name}' must be a comma-delimited string or null"
                )

            # --- 3) Capture any other optional keys as metadata ---
            core_keys = {'type', 'item_fields', 'report'}
            metadata = {
                key: value
                for key, value in cfg.items()
                if key not in core_keys
            }

            # --- 4) Normalize item_fields into a { fname: {type:…, …} } map ---
            normalized: dict[str, dict] = {}
            for fname, fdef in fields.items():
                if isinstance(fdef, str):
                    normalized[fname] = {'type': fdef}
                elif isinstance(fdef, dict):
                    if 'type' not in fdef:
                        raise ValueError(f"Field '{fname}' in section '{section_name}' needs a 'type' entry")
                    normalized[fname] = fdef.copy()
                else:
                    raise ValueError(
                        f"Field '{fname}' in section '{section_name}' must be a string or a map"
                    )

            # --- 5) Store it all ---
            schema[section_name] = {
                'fields':   normalized,  # required fields for ingestion & comparison
                'reports':  reports,     # either a list of strings or None
                'metadata': metadata     # free-form options for downstream tools
            }

        return schema
