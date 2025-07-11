# normalize.py

import re
from typing import Union

def can_parse_number(s: str) -> bool:
    """
    Returns True if s is a plain integer or float (no units),
    e.g. "123" or "-4.56".
    """
    return bool(re.fullmatch(r'-?\d+(\.\d+)?', s.strip()))

def detect_qual_vs_quant(values: list[str], threshold: float = 1.0) -> str:
    """
    If at least `threshold` fraction of non-missing values parse as numbers,
    treat as quantitative; else qualitative.
    """
    cleaned = [v for v in values if v not in ('-', 'N/A', '')]
    if not cleaned:
        return 'qualitative'

    num_count = sum(can_parse_number(v) for v in cleaned)
    frac = num_count / len(cleaned)
    return 'quantitative' if frac >= threshold else 'qualitative'

def infer_scale(numbers: list[Union[int, float]]) -> str:
    """
    Given a list of numeric values (ints or floats), returns:
      - 'discrete'   if only a small number of distinct values
      - 'continuous' otherwise
    """
    if not numbers:
        # No data -> treat as discrete by default
        return 'discrete'

    unique_count = len(set(numbers))
    # Threshold of 20 distinct values is arbitrary; adjust to taste
    return 'discrete' if unique_count < 20 else 'continuous'
