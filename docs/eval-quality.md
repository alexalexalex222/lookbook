# Routing And Page Quality Evaluation

Lookbook verifies two different things:

1. the router selected a defensible anchor and handled uncertainty correctly;
2. the generated frontend actually renders and behaves at the quality bar.

Neither result substitutes for the other.

## Routing Ledger

`evals/router/judgments.jsonl` is the versioned route/clarify ledger. It covers
train, calibration, and hidden splits, including historical failures, typos,
negation, sparse prompts, game surfaces, local-service verticals, and forbidden
anchor families.

```bash
lookbook --repo-root . visual-index
lookbook --repo-root . routing-eval \
  --profile hybrid_v5 \
  --output-dir evals/reports/router-v5
```

The command writes `routing-eval.json` and `routing-eval.html`. The hidden gate
requires:

- 100% pass rate;
- 100% route/clarify decision accuracy;
- zero forbidden-anchor violations.

`route_with_caution` counts as a route in the binary ledger while remaining
visible as a distinct runtime decision.

## Router V5

V5 preserves deterministic rules as the safety channel and adds:

- BM25 and character retrieval;
- structural source-profile retrieval;
- real screenshot pixel profiles;
- optional live local query embeddings;
- an optional bounded local reranker over the already-qualified top pool.

Build the optional local indexes:

```bash
lookbook --repo-root . visual-index
lookbook --repo-root . embedding-index --model nomic-embed-text:latest
```

Enable live dense queries only when a local embedding endpoint is available:

```bash
DESIGN_ROUTER_LIVE_EMBEDDINGS=1 \
  lookbook --repo-root . routing-eval --profile hybrid_v5
```

For the bounded reranker:

```bash
export DESIGN_ROUTER_RERANK_MODEL=qwen3.5:0.8b
export DESIGN_ROUTER_RERANK_URL=http://localhost:11434/api/generate
```

Use `rerank_mode="shadow"` first. Active mode can promote only an existing
candidate inside the configured score corridor and confidence floor. Candidate
escape, malformed JSON, endpoint failure, model abstention, low confidence, and
non-loopback endpoints all preserve the deterministic winner.

Optional `reference_image_paths` are resolved only inside the repository or
server roots declared by `DESIGN_ROUTER_REFERENCE_IMAGE_ROOTS`.

## Golden Build Arena

The Arena creates matched build inputs and evaluates baseline/candidate HTML.
Preparation writes:

- `baseline/PROMPT.md`;
- `routed/PROMPT.md`;
- `routed/PACKET.md`;
- `routed/ROUTE.json`;
- `PREPARED.json`.

```bash
lookbook --repo-root . arena \
  --phase prepare \
  --config evals/arena/example.json \
  --output-dir evals/arena/latest
```

After the same builder/model produces both pages, add `baseline_html` and
`routed_html` to each case and evaluate:

```bash
lookbook --repo-root . arena \
  --phase evaluate \
  --config evals/arena/example.json \
  --output-dir evals/arena/latest
```

Evaluation writes `results.json`, `report.md`, `report.html`, and full-page
screenshots for 1512, 1280, 768, 390, and 360 widths.

## Deterministic Gates

The static layer checks:

- title, language, and one-H1 heading flow;
- prohibited raster/external references;
- emoji in visible copy;
- labelled form controls;
- empty pages and repeated SVG warnings;
- focus, reduced-motion, domain, state, and structure signals.

The browser layer checks:

- browser availability when browser proof is requested;
- horizontal overflow;
- console and page errors;
- blocked network requests;
- body text size;
- 44px interactive targets;
- overlapping interactive controls;
- substantial content left opacity-hidden after a deterministic scroll sweep;
- nonblank rendered pages;
- painted canvas pixels for visible games.

The known-bad negative control must fail both the expected static checks and the
browser check. A candidate becomes eligible for human review only when the
negative control passes, the candidate clears deterministic gates, the result
does not regress from baseline, and the static quality delta is nonnegative.

Promotion is never automatic. The config must contain an explicit human review
with `approved: true` and `winner: "routed"`.

## Config Shape

```json
{
  "version": "1.0",
  "shared_instructions": "Use the same builder, model, and implementation budget.",
  "cases": [
    {
      "case_id": "arcade-racer",
      "request": {
        "surface": "game",
        "surface_kind": "game",
        "task": "Build a playable top-down arcade racer."
      },
      "domain_terms": ["racer", "checkpoint", "lap"],
      "baseline_html": "generated/arcade-baseline/index.html",
      "routed_html": "generated/arcade-routed/index.html",
      "human_review": {
        "approved": false,
        "winner": ""
      }
    }
  ]
}
```

Use `--no-browser` only for an explicitly static-only run. Browser unavailability
does not count as a pass when browser proof was requested.
