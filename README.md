# Lookbook

> **Design taste for any LLM** — turn any model (even a small one you run locally) into a senior frontend engineer.

[![License: MIT](https://img.shields.io/badge/license-MIT-111111.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-1f6feb.svg)
![MCP Server](https://img.shields.io/badge/MCP-server-111111.svg)
![Local-first](https://img.shields.io/badge/local--first-coding_agents-0f766e.svg)
![Anti-copy](https://img.shields.io/badge/anti--copy-enforced-7c3aed.svg)

<div align="center">

<a href="https://github.com/alexalexalex222/lookbook/raw/main/docs/assets/lookbook-demo.mp4">
  <img src="docs/assets/lookbook-demo.gif" alt="A live, cross-filtering analytics console built in one shot by Qwen 3.6 27B (dense) using Lookbook" width="860">
</a>

<sub><b>Built in one shot by Qwen&nbsp;3.6&nbsp;27B&nbsp;(dense)</b> — a model that runs on your own machine — using Lookbook. No frontier API, no design system handed to it, one prompt. &nbsp;▶&nbsp;<a href="https://github.com/alexalexalex222/lookbook/raw/main/docs/assets/lookbook-demo.mp4">Watch full quality</a></sub>

</div>

---

That console — coordinated cross-filtering across a donut, a brushable timeline, a
latency histogram, a region bar chart, a live event log, and an activity heatmap,
with honest synthetic data and zero invented metrics — was **not** built by a
frontier model. It was built by a 27B dense model you can run on a single machine.
The difference was Lookbook.

Lookbook is an open-source **MCP server and packet compiler** for frontend
generation. It takes a product brief, routes it through a curated, browser-verified
**original** design library (synthetic reference verticals and UI patterns built for
this project — not scraped sites), and returns a compact build packet: layout direction, source-backed
pattern snippets composed from the closest-matching references, hard implementation
constraints, and an enforced anti-copy contract. The model doesn't get a theme or a
template — it gets the structured design judgment it was missing.

> **Note:** The Python package is `lookbook-mcp` (install from source, below — not yet on
> PyPI). CLI entry points are `lookbook` and `lookbook-mcp`. Older `design-router-*`
> names remain as aliases.

## Why It Exists

General-purpose models flatten frontend work into the same few moves: soft
gradients, oversized heroes, equal card grids, invented "10,000+ users" social
proof, weak forms, and mobile layouts nobody checked. The model can write the code;
it just starts from weak design context. Lookbook fixes the *starting context* so
the first pass already looks like a product studio shipped it — and it does that for
**any** model, not one proprietary endpoint.

## What Ships

- **MCP stdio server** for OpenCode, Codex, Claude, Hermes, Grok, LM Studio, and any
  MCP-compatible runtime.
- **CLI packet compiler** for offline or scripted use.
- **Calibrated multi-stage routing engine** that classifies surface intent,
  ranks fuzzy/negation-aware task archetypes, applies pack-specific workflow
  signatures, gates incompatible anchor families, and returns `route`,
  `route_with_caution`, or `clarify` instead of expressing false confidence.
- **Packet renderer** with token modes from `micro` to full source excerpts, so the
  same library serves a 16k-context local model and a 1M-context agent.
- **Optional Pattern Shelf** that inlines a small set of role-matched Pattern Cards
  and exposes a larger qualified catalog across compatible golden sets. The primary
  anchor still owns the page; the builder may use zero, one, or several cards.
- **A curated, browser-verified design library** (`goldensets/`) — landing-page
  anchors plus 72 non-landing interactive patterns.
- **Validation, source-hygiene, anti-copy, route-alternative, and density tools.**
- **Versioned routing judgments and quality gates** across train, calibration, and
  hidden splits, with generated JSON/HTML audits and explicit hybrid disagreements.
- **Hybrid retrieval** that fuses deterministic rules, BM25, character similarity,
  a generated structural/pixel visual index, and optional frozen local embeddings.
  Dense query embeddings and pixel routing remain optional, so missing local
  services never make deterministic routing unavailable.
- **Router V5** with contained reference-screenshot matching and a bounded local
  candidate reranker. The model can reorder only the already-qualified top pool;
  it cannot admit a new pack or override a clarification decision.
- **Golden Build Arena** for reproducible baseline/candidate builds, deterministic
  static/browser gates, known-bad negative controls, full-page screenshots, and
  explicit human promotion.

## Build Week Proof

I built Golden Book and used Codex with GPT-5.6 to refine the routing system and
the golden sets used by the router. Codex helped me inspect weak generated
interfaces, compare original and routed builds, improve retrieval and source
hygiene, and verify the resulting interfaces in a browser. I made the product
and design decisions and iterated on the implementation.

The featured demonstration uses the same OpenCode MiMo builder and the same
martial-arts gym brief in both conditions:

- [Original prompt result](https://golden-book-martial-original.vercel.app)
- [Golden Book routed result](https://golden-book-martial-routed.vercel.app)
- [64-second comparison video](https://youtu.be/nn2zdjX-QC0)

These are controlled browser-tested examples, not a claim that one comparison
proves universal improvement. The example business is synthetic, and missing
business facts remain placeholders instead of invented claims.

## Anti-Copy Enforcement

Reference libraries are dangerous: the easy failure mode is a model that photocopies
a reference pack — reusing its placeholder business names, phone numbers,
testimonials, and awards on the target page. Lookbook treats every pack as a
**pattern source, never a page to clone**, and enforces that in code, not in a
disclaimer:

- **Reference identity is contraband on the target page.** Business names, phone
  numbers, emails, domains, reviews, awards, and stats in library source are
  classified as unsafe target-page material. The sanitizer (`sanitizer.py` /
  `scan_source_hygiene`) neutralizes identity / proof / raster leakage in excerpts
  before they enter a packet.
- **Every packet carries an Anti-Copy Contract** instructing the model to write fresh
  target-specific copy, use neutral labeled placeholders for missing proof, and
  compose its own layout — using the reference only for tone, hierarchy, and density.
- **No fabricated trust.** Generated pages get labeled placeholders (`[STAT_VALUE]`,
  `[TESTIMONIAL_QUOTE]`) instead of invented numbers and customers.
- **Raster and external-asset URLs are blocked** unless you supply assets for the
  target build.
- **Path-traversal containment** (`schemas.py`): a manifest cannot reference an
  absolute path or escape its pack directory with `..`, so a poisoned pack can't read
  arbitrary files. This is a validated schema invariant, regression-tested.

The library is a swatchbook, not a clipboard.

## Verification Rigor

Nothing enters the library — or a packet — on vibes.

- **Every pattern was browser-verified during curation.** Each was rendered in a real
  headless browser (Playwright) across desktop and mobile widths and checked for
  **zero console errors and zero horizontal overflow** before being banked. The
  Golden Build Arena now ships in the package; see `docs/eval-quality.md`.
- **`validate_design_router`** checks the whole library on demand: every manifest
  loads against a Pydantic schema, every source path and example directory resolves
  (no silent gaps), no path is absolute, and support banks have UX-role coverage.
  A separate **`hygiene`** audit reports identity/proof/raster hits in raw library
  source (expected in reference HTML); packets are sanitized before emit.
- **Routing is deterministic.** Pack and example selection use explicit secondary
  sort keys — the same brief always yields the same packet, so behavior is testable
  and reproducible.
- **Uncertainty is explicit.** Ambiguous or underspecified briefs preserve ranked
  archetype evidence, emit a provisional anchor, and include a concrete clarification
  question. Screenshot/proof constraints are kept out of semantic anchor scoring.
- **Routing vocabulary validates itself.** `validate_design_router` checks that every
  declared task alias resolves to its owning archetype, preferred/signature pack IDs
  exist, broad multi-pack intents have distinguishing signatures, and stale hierarchy
  references fail loudly.
- **Packet capacity is unbounded.** Relevance and hygiene decide what enters. Once
  selected, source files, Pattern Card fragments, contracts, and packet sections are
  emitted complete. Estimated tokens are telemetry only.
- **A public test suite** asserts route selection, complete packet/source rendering,
  arena rejection of application-level output caps, and anti-copy containment.
- **Reference-starvation auditing** (`donor_starvation_audit`) surfaces exactly
  which references were selected, rejected, or unavailable for any request, so routing
  is inspectable instead of a black box.
- **Zero-shot comparison frames** in `docs/assets/zero-shot-proofs/` (same brief,
  unrouted baseline vs Lookbook-routed output).

## Model Targets

Lookbook does not depend on one proprietary model. It's a frontend context layer for
anything that can follow a build packet and write code:

- frontier coding agents (GPT-5.x, Codex-style repo agents);
- strong open / local models — the demo above is **Qwen 3.6 27B (dense)**;
- local models through the same complete packet contract; callers must choose a
  runtime with enough context instead of asking the router to hide source;
- implementation-heavy agents via `code_profile: "code_first"`.

## Install

```bash
git clone https://github.com/alexalexalex222/lookbook.git
cd lookbook
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,mcp]"
lookbook --repo-root . validate
```

## CLI Usage

Export a packet:

```bash
lookbook --repo-root . export \
  --surface app.tool \
  --task "A live analytics dashboard: KPI cards, a brushable timeline, a sortable table, and a sidebar" \
  --output-dir /tmp/lookbook-packet \
  --token-mode unbounded \
  --stack html_css \
  --code-profile code_first
```

The export writes `PACKET.md` and `SOURCES.json`. Hand `PACKET.md` to the coding
agent that will build the page.

Useful commands:

```bash
lookbook --repo-root . list --examples   # browse the library
lookbook --repo-root . validate          # verify manifests, paths, and indexes
lookbook --repo-root . hygiene --pack-id frontier_pattern_bank_20260628_v1
lookbook --repo-root . visual-index      # index source structure and screenshot shape
lookbook --repo-root . routing-eval --output-dir evals/reports/router-latest
lookbook --repo-root . routing-eval --profile hybrid_v5 --output-dir evals/reports/router-v5

# Optional: build frozen dense vectors through a local Ollama-compatible endpoint.
lookbook --repo-root . embedding-index --model nomic-embed-text:latest

# Prepare matched baseline/routed prompts, then evaluate generated HTML.
lookbook --repo-root . arena --phase prepare --config evals/arena/example.json
lookbook --repo-root . arena --phase evaluate --config evals/arena/example.json
```

## MCP Usage

Point your MCP client at the stdio entry point (works in OpenCode, Codex, Claude,
Hermes, Grok, LM Studio):

```json
{
  "mcpServers": {
    "lookbook": {
      "command": "/absolute/path/to/.venv/bin/lookbook-mcp",
      "args": ["--repo-root", "/absolute/path/to/lookbook"]
    }
  }
}
```

Primary tool: `resolve_design_context`. Also available: `inspect_design_library`,
`get_pattern_card`, `get_source_excerpt`, `export_opencode_bundle`, `route_alternatives`,
`donor_starvation_audit`, `code_density_metrics`, `audit_source_hygiene`,
`routing_quality_audit`, `build_visual_routing_index`,
`build_design_embedding_index`, `run_golden_build_arena`, and
`validate_design_router`.

`resolve_design_context` defaults to `route_profile="hybrid_v4"`. Set
`route_profile="hybrid_shadow_v1"` to observe hybrid winners without allowing the
retrieval bonus to change the selected anchor. Set `route_profile="hybrid_v5"` to
add screenshot-pixel matching and bounded local reranking. Frozen embeddings are
used for health/coverage by default; set `DESIGN_ROUTER_LIVE_EMBEDDINGS=1` to
enable a live query vector through `DESIGN_ROUTER_EMBED_URL`.

Optional pattern retrieval is enabled by default. `optional_pattern_count` requests
an upper bound, not a quota. Token modes never lower that request or trim selected
cards. The router hard-gates foreign domains, fills uncovered priority roles, and
stops at the relevance elbow instead of padding the shelf. Each inlined Pattern Card
includes its job, fit axes, when/when-not guidance, states, responsive behavior,
invariants, dependencies, integration guidance, exact provenance, and complete
sanitized code for the selected fragment. A larger
qualified catalog remains available without loading its code; expand one item with
`get_pattern_card` using the same request and exact `pattern_id`. Set
`include_optional_patterns=false` to disable both the shelf and catalog.

V5 reranking is local-only by default:

```bash
export DESIGN_ROUTER_RERANK_MODEL=qwen3.5:0.8b
export DESIGN_ROUTER_RERANK_URL=http://localhost:11434/api/generate
```

Then send `rerank_mode: "shadow"` to observe the decision or
`rerank_mode: "active"` to allow a bounded promotion inside the qualified
candidate pool. Non-loopback endpoints are rejected unless the server operator
explicitly sets `DESIGN_ROUTER_ALLOW_REMOTE_RERANK=1`.

Recommended request shape:

```json
{
  "surface": "app.tool",
  "task": "Build a live analytics console with cross-filtering charts and a data table",
  "stack": "html_css",
  "route_profile": "hybrid_v5",
  "rerank_mode": "shadow",
  "reference_image_paths": ["references/target-direction.png"],
  "token_mode": "unbounded",
  "optional_pattern_count": 10,
  "code_profile": "code_first",
  "packet_intent": "implementation_blueprint"
}
```

## Library Contents

The current library index contains 92 routed packs: 88 anchors and 4 support
banks.

- **anchor packs** for SaaS dashboards, combat sports, water service, live commerce,
  developer docs, luxury/editorial pages, product/spec pages, interactive
  instruments, native arcade/tactics games, finance terminals, garden care,
  legal/business pages, cabinetry, flooring, and other local-service surfaces;
- the **frontier pattern bank** (`frontier_pattern_bank_20260628_v1`): **72**
  browser-verified, non-landing-page UI patterns — dashboards, data-viz, editors,
  app shells, games, and real-time 3D/canvas scenes — so Lookbook routes for *all*
  design work, not just marketing pages;
- **support banks** for synthetic local-service page structures and the localhost
  full-site pattern bank;
- **shared atoms** for navigation, heroes, cards, forms, tabs, FAQs, pricing, stats,
  galleries, footers, and interaction states.

## Verification

```bash
pytest tests -q                    # route + render + anti-copy guards
lookbook --repo-root . validate    # validate the whole library
```

## Project Layout

```text
src/design_router_mcp/        canonical Python package
goldensets/                   public routed design library
tests/                        public smoke + hardening tests
docs/                         assets, evaluation notes
server.json                   MCP/server manifest
```

## License

MIT. See `LICENSE`.
