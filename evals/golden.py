"""
Load the golden evaluation dataset.

The golden dataset is a YAML file of questions where we know the right
answers — which sources should be cited, which key claims should appear,
and what output mode (comparison, lit-review, notes) to use.

This is our ground truth for measuring whether Lecturn is working.
We compare Lecturn's actual output against these expected values
to score faithfulness, completeness, and format validity.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml


GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_dataset.yaml"


@dataclass
class GoldenExample:
    question: str
    mode: str                        # "comparison" | "lit-review" | "notes"
    expected_sources: list[str]      # source titles that must be cited
    expected_key_claims: list[str]   # claims the output should contain


def load_golden_dataset() -> list[GoldenExample]:
    """
    Load the golden dataset from YAML and return as a list of GoldenExample objects.

    Each entry has:
        - question: str — the query to send to Lecturn
        - mode: str — one of "comparison", "lit-review", "notes"
        - expected_sources: list[str] — titles that should be cited
        - expected_key_claims: list[str] — claims the output should contain

    Returns:
        list of GoldenExample dataclass instances
    """
    raw = yaml.safe_load(GOLDEN_DATASET_PATH.read_text())
    examples = []
    for entry in raw.get("examples", []):
        examples.append(GoldenExample(
            question=entry["question"],
            mode=entry["mode"],
            expected_sources=entry["expected_sources"],
            expected_key_claims=entry["expected_key_claims"],
        ))
    return examples


if __name__ == "__main__":
    dataset = load_golden_dataset()
    print(f"Loaded {len(dataset)} golden examples.\n")

    modes = {}
    for ex in dataset:
        modes[ex.mode] = modes.get(ex.mode, 0) + 1

    print("Breakdown by mode:")
    for mode, count in sorted(modes.items()):
        print(f"  {mode}: {count}")

    print()
    for i, ex in enumerate(dataset, 1):
        sources = len(ex.expected_sources)
        claims = len(ex.expected_key_claims)
        # comparison / lit-review questions must draw from >= 2 sources.
        # notes questions are about a single paper/post so 1 source is correct.
        min_sources = 1 if ex.mode == "notes" else 2
        assert sources >= min_sources, (
            f"Example {i} ({ex.mode}) has only {sources} expected_sources (need >= {min_sources})"
        )
        assert claims >= 2, f"Example {i} has only {claims} expected_key_claims (need >= 2)"

    print("All examples have >= 2 expected_key_claims and correct source counts per mode.")
    print()
    print("Sample (first example):")
    ex = dataset[0]
    print(f"  question: {ex.question}")
    print(f"  mode:     {ex.mode}")
    print(f"  sources:  {ex.expected_sources}")
    print(f"  claims:   {ex.expected_key_claims}")
