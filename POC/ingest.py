# ingest.py

import json
from typing import Any

class JsonParser:
    """
    Given the schema dict from SchemaLoader, validate & pull in the JSON.

    Expects schema:
      {
        section_name: {
          'fields':   { fname: {type:…, …}, … },
          'reports':  [... ] or None,
          'metadata': { … }
        },
        …
      }
    """

    def __init__(self, schema: dict[str, dict[str, Any]]):
        self.schema = schema

    def parse(self, json_path: str) -> dict[str, list[dict]]:
        with open(json_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        parsed: dict[str, list[dict]] = {}
        for section_name, section_cfg in self.schema.items():
            field_defs = section_cfg['fields']

            if section_name not in raw:
                raise KeyError(f"Missing section: '{section_name}'")

            entries = raw[section_name]
            if not isinstance(entries, list):
                raise TypeError(f"Section '{section_name}' must be a list, got {type(entries).__name__}")

            validated: list[dict] = []
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise TypeError(f"Entry #{idx} in '{section_name}' is not an object")

                # Check each required field is present
                for fname in field_defs:
                    if fname not in entry:
                        raise KeyError(f"Entry #{idx} in '{section_name}' missing field '{fname}'")

                validated.append(entry)

            parsed[section_name] = validated

        return parsed
