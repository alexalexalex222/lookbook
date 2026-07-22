# Optional Pattern Judgment Ledger

Store real human reviews as one JSON object per line in
`evals/patterns/judgments.jsonl`. Validate each row against
`judgments.schema.json`.

Record a judgment only after reviewing the expanded Pattern Card or a generated
baseline-versus-pattern build. Do not infer approval from a route score.

Recommended review loop:

1. Resolve the brief and record its `route_trace_id`.
2. Review the inlined cards and qualified catalog.
3. Expand one candidate with `get_pattern_card`.
4. Build or render the baseline and candidate when the decision is visual.
5. Record one verdict per pattern with artifact paths and concrete notes.

The ledger is intentionally absent until real reviews exist. Do not seed it with
synthetic approvals.
