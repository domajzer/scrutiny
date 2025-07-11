# ingest.py

import json

class JsonParser:
    """
    Given the schema dict from SchemaLoader, validate & pull in the JSON.
    """
    def __init__(self, schema):
        self.schema = schema

    def parse(self, json_path):
        with open(json_path, 'r') as f:
            raw = json.load(f)

        parsed = {}
        for section_name, field_defs in self.schema.items():
            if section_name not in raw:
                raise KeyError(f"Missing section: {section_name}")

            entries = raw[section_name]
            if not isinstance(entries, list):
                raise TypeError(f"Section '{section_name}' must be a list")

            validated = []
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise TypeError(f"Entry #{idx} in '{section_name}' is not an object")
                # Check required fields are present
                for fname in field_defs:
                    if fname not in entry:
                        raise KeyError(
                            f"Entry #{idx} in '{section_name}' missing field '{fname}'"
                        )
                validated.append(entry)
            parsed[section_name] = validated

        return parsed
