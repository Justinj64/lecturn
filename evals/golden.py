"""
Load the golden evaluation dataset.

The golden dataset is a YAML file of questions where we know the right
answers — which sources should be cited, which key claims should appear,
and what output mode (comparison, lit-review, notes) to use.

This is our ground truth for measuring whether Lecturn is working.
We compare Lecturn's actual output against these expected values
to score faithfulness, completeness, and format validity.
"""
from pathlib import Path

import yaml


GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_dataset.yaml"


def load_golden_dataset() -> list[dict]:
    """
    Load the golden dataset from YAML and return as a list of dicts.

    Each entry has:
        - question: str — the query to send to Lecturn
        - mode: str — one of "comparison", "lit-review", "notes"
        - expected_sources: list[str] — titles that should be cited
        - expected_key_claims: list[str] — claims the output should contain

    Returns:
        list of golden example dicts
    """
    raise NotImplementedError("Day 11: implement golden dataset loader")
