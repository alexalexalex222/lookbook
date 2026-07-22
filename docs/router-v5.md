# Router V5 Architecture

Router V5 is an opt-in promotion candidate layered on top of the calibrated V4
router. V4 remains the default until repeated Golden Build Arena evidence shows
that V5 improves generated pages without route regressions.

## Decision Pipeline

1. Normalize surface, workflow archetype, vertical, negation, and constraints.
2. Hard-gate incompatible families.
3. Score deterministic route evidence.
4. Fuse rules, BM25, character, structural visual, optional pixel, and optional
   dense channels.
5. Compute route confidence and clarification state.
6. Optionally ask a local model to rerank only the top qualified candidates.
7. Reject any candidate escape, malformed response, low-confidence choice,
   out-of-corridor promotion, or promotion over a clarification decision.
8. Hard-gate the primary support bank by surface family, then hard-gate support
   examples by recognized domain and game archetype before scoring.
9. Retrieve a qualified catalog of optional Pattern Cards, then inline only the
   cards that cover a priority job before the relevance elbow.
10. Render the packet with the complete route trace.

## Optional Pattern Shelf

The primary anchor remains the only composition and identity owner. A separate
retrieval lane scores partial patterns across all support banks, extracts the best
section job from each selected example, and may include at most one same-family
runner-up anchor as a summary-only treatment card.

Selection is deterministic and diversity-aware:

- the requested count is a ceiling, never a quota;
- token-mode labels never lower the requested count or trim selected cards;
- foreign domains are rejected before ranking, including archetype hints;
- neutral donors require a concrete requested mechanic rather than broad preset fit;
- games admit only native game-domain support fragments;
- one extracted section per example, with duplicate source content removed;
- score axes remain inspectable: domain, mechanic, quality, surface, bank, lexical,
  conflict, and excerpt fit;
- final per-pack caps are hard and cannot be relaxed to fill slots;
- priority roles are filled first, then an elbow stop withholds redundant filler;
- auxiliary anchors are capped at one, carry high identity risk, and emit no markup
  or CSS.

Every inlined card carries exact pack, example, section, score axes, domain/mechanic/
quality fit, identity risk, job, when/when-not guidance, states, responsive behavior,
invariants, dependencies, integration guidance, and sanitized source provenance.
Selected markup and CSS fragments are emitted complete. Builders may use zero, one,
or several cards. Choosing none is valid.

Qualified cards that are not inlined remain in a cheap catalog. Call
`get_pattern_card` with the same request, exact `pattern_id`, and tier `S`, `M`, or
`L` to expand one card. The tool rejects patterns that were not qualified for that
request. Raw runner-up-anchor code is never emitted by this expansion path.

## Primary Support Lane

Primary support donors are stricter than optional cards because their snippets
appear earlier in the packet:

- game requests can select only support banks that declare `game_ui`;
- recognized local-service domains select only local-service support banks;
- recognized local-service examples must match the request domain;
- arcade and tactics examples must belong to the active game archetype hint set;
- game routes use one primary support example, leaving additional same-subgenre
  mechanics in the optional catalog;
- domain and archetype rejections are counted in donor-starvation diagnostics.

## Pixel Retrieval

`lookbook visual-index` decodes real screenshot pixels and stores a compact,
dependency-optional profile:

- luminance and contrast;
- saturation, warmth, and colorfulness;
- dark/light ratios;
- edge density and entropy;
- horizontal/vertical imbalance;
- center emphasis;
- dominant color buckets.

Pillow is used when available. A standard-library PNG decoder keeps the channel
available for common 8-bit non-interlaced PNG screenshots without introducing a
production dependency.

Text directions such as dark, warm, restrained, cool, vivid, dense, airy, and
high contrast become a target profile. Optional local reference screenshots can
also provide the target profile.

Pixel rank weight is reduced automatically when screenshot coverage is sparse.
Run `lookbook validate` to inspect current coverage instead of assuming every
anchor has visual evidence.

## Local Reranker

The reranker is deliberately narrow:

- loopback endpoint by default;
- maximum five candidates;
- strict JSON;
- temperature zero with no application-level completion-token ceiling;
- candidate IDs must come from the supplied pool;
- active promotion requires the confidence floor and score corridor;
- deterministic clarification always wins;
- every failure mode preserves the existing winner.

This makes the local model a tie-breaker, not a second uncontrolled router.

## Native Game Routing

V5 includes a dedicated `website.game` family, `browser_game` vertical, and
specific arcade-racer and turn-based-tactics archetypes. Game requests hard-gate
to native game anchors so spreadsheets, dashboards, and interactive instruments
cannot own game identity.

Current native game anchors:

- `neon_apex_arcade_racer_v1`;
- `ashvault_dungeon_tactics_v1`.

## Promotion Policy

Do not make V5 the default based only on routing-ledger parity. Require:

- full routing ledger pass;
- known-bad negative control pass;
- browser proof at every configured viewport;
- no candidate regression;
- repeated routed-vs-unrouted page wins;
- explicit human approval.
