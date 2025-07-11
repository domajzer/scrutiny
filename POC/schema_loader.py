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
      ...
    """
    def __init__(self, yaml_path):
        self.yaml_path = yaml_path

    def load(self):
        with open(self.yaml_path, 'r') as f:
            raw = yaml.safe_load(f)

        schema = {}
        for section_name, cfg in raw.get('sections', {}).items():
            if cfg.get('type') != 'list':
                raise ValueError(f"Section '{section_name}' must be declared as a list")
            
            fields = cfg.get('item_fields', {})
            if not isinstance(fields, dict):
                raise ValueError(f"'item_fields' for section '{section_name}' must be a dict")

            # Normalize each field definition to a dict:
            normalized = {}
            for fname, fdef in fields.items():
                if isinstance(fdef, str):
                    # simple shorthand: "string" → {type: "string"}
                    normalized[fname] = {'type': fdef}
                elif isinstance(fdef, dict):
                    # already {type: ..., maybe category: ...}
                    if 'type' not in fdef:
                        raise ValueError(f"Field '{fname}' needs a 'type' entry")
                    normalized[fname] = fdef.copy()
                else:
                    raise ValueError(
                        f"Field '{fname}' in section '{section_name}' must be string or map"
                    )
            
            schema[section_name] = normalized
        return schema
