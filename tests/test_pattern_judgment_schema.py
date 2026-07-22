import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pattern_judgment_schema_defines_real_review_outcomes():
    schema = json.loads(
        (ROOT / "evals" / "patterns" / "judgments.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["additionalProperties"] is False
    assert {"judgment_id", "request", "pattern_id", "verdict", "reviewer", "reviewed_at", "notes"} <= set(
        schema["required"]
    )
    verdicts = set(schema["properties"]["verdict"]["enum"])
    assert {"useful", "redundant", "foreign_domain", "identity_risk", "broken_excerpt"} <= verdicts
