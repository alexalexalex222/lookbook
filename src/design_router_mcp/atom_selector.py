"""Deterministic relevance selection for first-party reference atoms.

The shared-atom library is large (foundation tokens + many full components). This
module scores each atom's ``meta.json``-derived metadata against the request
(surface / inferred ux_roles / tone / tags+motifs) and returns a stable,
relevance-only selection.

Rules:
- ``foundation_design_tokens_v1`` is included first only on compatible website
  surfaces (the token contract every website component reads from).
- Meta atoms are ranked by a deterministic score; ties break on ``atom_id``.
- Atoms must have a real request-role or tag/category match. The selector never
  fills a mode quota with unrelated components.
- Legacy atoms (no ``meta.json``) are selectable only as lower-priority fallback,
  after every positively-scored meta atom.
- No randomness anywhere: same inputs -> same ordered output.
"""

from __future__ import annotations

from .schemas import AtomSnippet

FOUNDATION_ATOM_ID = "foundation_design_tokens_v1"

# Scoring weights (deterministic integers).
_W_SURFACE_EXACT = 6
_W_SURFACE_WILDCARD = 2
_W_UX_ROLE = 8
_W_TAG = 3
_W_TONE = 2
_W_META_BASE = 1       # any meta atom gets a small floor so it outranks legacy
_W_LEGACY_BASE = 0     # legacy (no-meta) atoms are pure fallback


def atom_budget_for_mode(mode: str) -> None:
    """Compatibility shim: token modes no longer impose an atom count ceiling."""
    return None


def _surface_score(atom: AtomSnippet, surface: str) -> int:
    if not atom.surfaces:
        return 0
    surface = (surface or "").lower()
    family = surface.split(".", 1)[0] if surface else ""
    best = 0
    for raw in atom.surfaces:
        s = raw.lower()
        if not s:
            continue
        if s == surface:
            best = max(best, _W_SURFACE_EXACT)
        elif s.endswith(".*") and family and s.startswith(family):
            best = max(best, _W_SURFACE_WILDCARD)
        elif s == f"{family}.*":
            best = max(best, _W_SURFACE_WILDCARD)
    return best


def _surface_compatible(atom: AtomSnippet, surface: str, surface_kind: str) -> bool:
    if not atom.surfaces:
        return surface_kind not in {"game", "instrument"}
    declared = {value.lower() for value in atom.surfaces}
    kind = (surface_kind or "").lower()
    if kind == "game":
        return any("game" in value for value in declared)
    if kind == "instrument":
        return any(
            token in value
            for value in declared
            for token in ("instrument", "interactive_experience", "audio")
        )
    if kind in {"app", "dashboard"}:
        return any(
            token in value
            for value in declared
            for token in ("app", "dashboard", "tool")
        )
    if kind in {"landing", "docs"}:
        return any(value.startswith("website") for value in declared)
    return _surface_score(atom, surface) > 0


def _semantic_overlap(
    atom: AtomSnippet,
    *,
    request_roles: set[str],
    tag_terms: set[str],
) -> tuple[set[str], set[str]]:
    roles = {role.lower() for role in atom.ux_roles}
    role_overlap = roles.intersection(request_roles)
    atom_tags = {tag.lower() for tag in atom.tags}
    if atom.category:
        atom_tags.add(atom.category.lower())
    tag_overlap = atom_tags.intersection(tag_terms)
    return role_overlap, tag_overlap


def score_atom(
    atom: AtomSnippet,
    *,
    surface: str,
    request_roles: set[str],
    tone: set[str],
    tag_terms: set[str],
) -> int:
    """Deterministic relevance score for a single atom against the request."""
    if not atom.has_meta:
        # Legacy atoms carry no metadata; they only ever serve as fallback filler.
        return _W_LEGACY_BASE
    score = _W_META_BASE
    score += _surface_score(atom, surface)
    roles = {r.lower() for r in atom.ux_roles}
    score += _W_UX_ROLE * len(roles.intersection({r.lower() for r in request_roles}))
    atom_tags = {t.lower() for t in atom.tags}
    if atom.category:
        atom_tags.add(atom.category.lower())
    score += _W_TAG * len(atom_tags.intersection({t.lower() for t in tag_terms}))
    atom_tone = {t.lower() for t in atom.tone}
    score += _W_TONE * len(atom_tone.intersection({t.lower() for t in tone}))
    return score


def select_shared_atoms(
    atoms: list[AtomSnippet],
    *,
    mode: str,
    surface: str,
    request_roles: set[str],
    surface_kind: str = "",
    tone: set[str] | list[str] | None = None,
    tag_terms: set[str] | list[str] | None = None,
    covered_roles: set[str] | list[str] | None = None,
) -> list[AtomSnippet]:
    """Return a stable, relevance-ordered atom selection.

    The compatible foundation is first when present. Every remaining atom must
    solve a requested role or match a requested tag/category. Deterministic:
    identical inputs yield identical ordering.
    """
    if not atoms:
        return []
    tone_set = {t.lower() for t in (tone or [])}
    tag_set = {t.lower() for t in (tag_terms or [])}
    role_set = {r.lower() for r in (request_roles or set())}
    already_covered = {r.lower() for r in (covered_roles or set())}

    foundation = next((a for a in atoms if a.atom_id == FOUNDATION_ATOM_ID), None)
    rest = [a for a in atoms if a.atom_id != FOUNDATION_ATOM_ID]

    scored = []
    for atom in rest:
        if not _surface_compatible(atom, surface, surface_kind):
            continue
        role_overlap, tag_overlap = _semantic_overlap(
            atom,
            request_roles=role_set,
            tag_terms=tag_set,
        )
        if not role_overlap and not tag_overlap:
            continue
        scored.append(
            (
                score_atom(
                    atom,
                    surface=surface,
                    request_roles=role_set,
                    tone=tone_set,
                    tag_terms=tag_set,
                ),
                atom,
                role_overlap,
                tag_overlap,
            )
        )
    # Stable: highest score first, then alphabetical atom_id. has_meta floor keeps
    # legacy atoms below any meta atom; meta atoms with zero topical overlap still
    # sort above legacy via the meta base score.
    scored.sort(key=lambda item: (-item[0], item[1].atom_id))

    selected: list[AtomSnippet] = []
    if foundation is not None and _surface_compatible(foundation, surface, surface_kind):
        selected.append(foundation)
    category_counts: dict[str, int] = {}
    covered = set(already_covered)
    for _, atom, role_overlap, tag_overlap in scored:
        new_roles = role_overlap.difference(covered)
        category = (atom.category or "").lower()
        direct_category_match = bool(category and category in tag_overlap)
        if role_overlap and not new_roles and not tag_overlap:
            continue
        if category and category_counts.get(category, 0) >= 1 and not new_roles and not direct_category_match:
            continue
        selected.append(atom)
        covered.update(role_overlap)
        if category:
            category_counts[category] = category_counts.get(category, 0) + 1
    return selected
