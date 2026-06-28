# Lookbook

> **Design taste for any LLM** — turn any model (even a small local one) into a senior frontend designer.

[![License: MIT](https://img.shields.io/badge/license-MIT-111111.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-1f6feb.svg)
![MCP Server](https://img.shields.io/badge/MCP-server-111111.svg)
![Local-first](https://img.shields.io/badge/local--first-coding_agents-0f766e.svg)

Lookbook is an open-source MCP server and packet compiler for
frontend generation. It takes a product brief, routes it through a curated design
library, and returns a compact build packet with layout direction, source-backed
patterns, implementation constraints, and anti-copy rules.

It is built for coding agents that can write code but need sharper design
context before they start. The packets are model-agnostic: use them with GPT-5.5
class agents, Codex-style coding agents, or strong open/local coding models in
the Qwen 3.6 27B class. The output is not a theme, template, or screenshot
clone. It is a structured brief that tells the model what pattern family to use,
what details to adapt, and what it must not copy.

## What Ships

- MCP stdio server for LM Studio, OpenCode, Codex-compatible clients, and other
  agent runtimes.
- CLI packet compiler for offline or scripted use.
- Routing engine that scores frontend briefs against anchor packs and support
  banks.
- Packet renderer with token modes from `micro` through larger source excerpts.
- Full public golden-set library in `goldensets/` plus packaged copies under
  `src/design_router_mcp/goldensets/`.
- Validation, donor hygiene, source excerpt, route alternative, and density
  tools.

## Model Targets

Lookbook does not depend on one proprietary model. It is a
front-end context layer for any model that can follow a build packet and write
usable code.

Good fits include:

- GPT-5.5 class coding agents;
- Codex-style repo agents;
- local or open coding models such as Qwen 3.6 27B;
- smaller-context models using `token_mode: "micro"` or `token_mode: "compact"`;
- stronger agents using `code_profile: "code_first"` and larger source excerpts.

## Why It Exists

General-purpose models tend to flatten frontend work into the same few moves:
soft gradients, oversized heroes, equal card grids, invented social proof, weak
forms, and mobile layouts nobody checked. Lookbook fixes the
starting context. It gives the model a stronger design system before code is
written.

The server is especially useful when you want generated UI to inherit real
structure from strong examples without stealing a donor site's identity, copy,
assets, testimonials, or claims.

## Golden Sets, Not Copy Sets

The golden sets are pattern sources. They are not pages to clone.

A packet can include source excerpts, component structure, density cues, section
ordering, typography patterns, interaction states, and visual rules. The packet
also carries guardrails that tell the model to write new page copy for the target
brief and to avoid copying donor identity.

The anti-copy layer exists for this exact reason:

- donor business names, phone numbers, emails, domains, reviews, awards, and
  claims are treated as unsafe target-page material;
- source copy is used for tone, hierarchy, and density, not as raw text to paste;
- raster images and external asset URLs are blocked unless the user supplies
  assets for the target build;
- generated pages should use fresh target-specific copy, neutral placeholders
  for missing proof, and their own visual composition;
- support-bank examples are used to triangulate layout patterns, not to recreate
  one donor page.

## Zero-Shot Visual Proof

These frames come from local screen recordings of the same speaker-company
prompt run zero-shot. The two comparison clips are the first and second attempts
without the Lookbook packet. The selected run uses the packet-guided MCP
flow. This is visual evidence for first-pass direction, not a formal benchmark.

| First try, no packet | Second try, no packet | Packet-guided run |
|---|---|---|
| <img src="docs/assets/zero-shot-proofs/baseline-try-1.jpg" alt="First zero-shot speaker-company attempt without the Lookbook packet" width="260"> | <img src="docs/assets/zero-shot-proofs/baseline-try-2.jpg" alt="Second zero-shot speaker-company attempt without the Lookbook packet" width="260"> | <img src="docs/assets/zero-shot-proofs/mcp-good-01.jpg" alt="Packet-guided zero-shot speaker-company homepage generated with Lookbook" width="260"> |

The packet-guided run carried the speaker-company direction past the hero into
deeper product sections and inquiry flow:

<img src="docs/assets/zero-shot-proofs/mcp-good-02.jpg" alt="Interior section from the packet-guided speaker-company homepage" width="720">

## Install

```bash
git clone https://github.com/alexalexalex222/lookbook.git
cd lookbook
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,mcp]"
PYTHONPATH=src python -m design_router_mcp.cli --repo-root . validate
```

## CLI Usage

Export a packet:

```bash
PYTHONPATH=src python -m design_router_mcp.cli --repo-root . export \
  --surface website.local_service \
  --task "Build a serious martial arts gym homepage" \
  --output-dir /tmp/design-router-gpt-5.5-mcp-packet \
  --token-mode compact \
  --stack html_css \
  --code-profile code_first
```

The export writes:

```text
/tmp/design-router-gpt-5.5-mcp-packet/PACKET.md
/tmp/design-router-gpt-5.5-mcp-packet/SOURCES.json
```

Give `PACKET.md` to the coding agent that will build the page.

Useful CLI commands:

```bash
PYTHONPATH=src python -m design_router_mcp.cli --repo-root . list
PYTHONPATH=src python -m design_router_mcp.cli --repo-root . validate
PYTHONPATH=src python -m design_router_mcp.cli --repo-root . hygiene --pack-id localhost_fullsite_pattern_bank_20260622_v1
```

## MCP Usage

Install the package in a virtual environment, then point your MCP client at the
stdio entry point:

```json
{
  "mcpServers": {
    "design-router-gpt-5.5-mcp": {
      "command": "/absolute/path/to/.venv/bin/design-router-gpt-5.5-mcp",
      "args": ["--repo-root", "/absolute/path/to/design-router-gpt-5.5-mcp"]
    }
  }
}
```

Main tool:

```text
resolve_design_context
```

Additional tools:

```text
inspect_design_library
get_source_excerpt
export_opencode_bundle
route_alternatives
donor_starvation_audit
code_density_metrics
audit_source_hygiene
validate_design_router
```

Recommended request shape:

```json
{
  "surface": "website.local_service",
  "task": "Build a premium homepage for a speaker company",
  "stack": "html_css",
  "token_mode": "compact",
  "code_profile": "code_first",
  "packet_intent": "implementation_blueprint"
}
```

## Library Contents

The public library currently includes 23 routed packs:

- anchor packs for SaaS dashboards, combat sports, water service, live commerce,
  developer docs, luxury/editorial pages, product/spec pages, interactive
  instruments, finance terminals, garden care, legal/business pages, cabinetry,
  flooring, and other local-service surfaces;
- the **frontier pattern bank** (`frontier_pattern_bank_20260628_v1`): 72
  browser-verified, non-landing-page UI patterns — dashboards, data-viz, editors,
  app shells, games, and real-time 3D/canvas scenes — so Lookbook routes for *all*
  design work, not just marketing pages;
- support banks for GA SMB page structures and the localhost full-site pattern
  bank captured on 2026-06-22;
- shared atoms for navigation, heroes, cards, forms, tabs, FAQs, pricing,
  stats, galleries, footers, and interaction states.

## Verification

Run the public smoke tests:

```bash
PYTHONPATH=src python -m pytest tests -q
```

Validate the design library:

```bash
PYTHONPATH=src python -m design_router_mcp.cli --repo-root . validate
```

Build a wheel when changing package metadata or entry points:

```bash
python -m pip wheel . --no-deps -w /tmp/design-router-gpt-5.5-mcp-wheel
```

## Project Layout

```text
src/design_router_mcp/        canonical Python package
goldensets/                   public routed design library
tests/                        public smoke tests
docs/eval-quality.md          quality and evaluation notes
server.json                   MCP/server manifest
CANONICAL_SOURCE.md           source-tree boundary notes
MIGRATION.md                  cleanup and migration notes
```

## License

MIT. See `LICENSE`.
