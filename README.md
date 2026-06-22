# Design Router GPT-5.5 MCP

Design Router GPT-5.5 MCP is an open-source MCP server and packet compiler for
frontend generation. It takes a product brief, routes it through a curated design
library, and returns a compact build packet with layout direction, source-backed
patterns, implementation constraints, and anti-copy rules.

It is built for coding agents that can write code but need sharper design
context before they start. The output is not a theme, template, or screenshot
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

## Why It Exists

General-purpose models tend to flatten frontend work into the same few moves:
soft gradients, oversized heroes, equal card grids, invented social proof, weak
forms, and mobile layouts nobody checked. Design Router GPT-5.5 MCP fixes the
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

## Install

```bash
git clone https://github.com/alexalexalex222/design-router-gpt-5.5-mcp.git
cd design-router-gpt-5.5-mcp
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

The public library currently includes 22 routed packs:

- anchor packs for SaaS dashboards, combat sports, water service, live commerce,
  developer docs, luxury/editorial pages, product/spec pages, interactive
  instruments, finance terminals, garden care, legal/business pages, cabinetry,
  flooring, and other local-service surfaces;
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
