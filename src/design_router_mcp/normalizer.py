from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from .rules import RoutingRules, load_routing_rules
from .schemas import ArchetypeCandidate, DesignContextRequest, NormalizedRequest

TOKEN_RE = re.compile(r"[a-z0-9]+")
INLINE_NEGATIVE_RE = re.compile(r"(?:do not|don't|avoid|without|not|no)\s+([^,.;\n]+)", re.IGNORECASE)
PROOF_CONSTRAINT_RE = re.compile(
    r"\b(?:screenshot|viewport|pixel[- ]?perfect|full[- ]?page capture)\b|\b\d{3,4}\s*x\s*\d{3,4}\b",
    re.IGNORECASE,
)
ARCHETYPE_GENERIC_TOKENS = {
    "app",
    "application",
    "build",
    "dashboard",
    "design",
    "interface",
    "page",
    "screen",
    "tool",
    "website",
    "workspace",
}
LANDING_INTENT_TOKENS = {"homepage", "landing", "marketing", "hero", "campaign"}
STRUCTURED_LANDING_SURFACE_PREFIXES = (
    "website.homepage",
    "website.landing",
    "website.hero",
)
SURFACE_KIND_ALIASES = {
    "app": "app",
    "dashboard": "app",
    "workspace": "app",
    "tool": "app",
    "instrument": "instrument",
    "game": "game",
    "docs": "docs",
    "documentation": "docs",
    "landing": "landing",
    "homepage": "landing",
    "hero": "landing",
    "unknown": "unknown",
}


def tokenize(parts: Iterable[str]) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        if part is None:
            continue
        tokens.update(TOKEN_RE.findall(str(part).lower()))
    return tokens


def extract_inline_negative_tokens(parts: Iterable[str]) -> set[str]:
    negative_tokens: set[str] = set()
    for part in parts:
        lower = str(part).lower()
        for match in INLINE_NEGATIVE_RE.finditer(lower):
            negative_tokens.update(TOKEN_RE.findall(match.group(1)))
    return negative_tokens


def strip_inline_negative_clauses(parts: Iterable[str]) -> list[str]:
    return [INLINE_NEGATIVE_RE.sub(" ", str(part)) for part in parts]


def request_tokens(request: DesignContextRequest, *, include_negative: bool = False) -> set[str]:
    semantic_constraints = [constraint for constraint in request.constraints if not PROOF_CONSTRAINT_RE.search(constraint)]
    positive = tokenize([request.surface, request.task, request.layout_mode, request.stack, *request.tone, *semantic_constraints])
    if include_negative:
        return positive
    return positive.difference(negative_tokens(request))


def negative_tokens(request: DesignContextRequest) -> set[str]:
    tokens = tokenize(request.anti_patterns)
    tokens.update(extract_inline_negative_tokens([request.task, *request.constraints]))
    return tokens


def _tags_from_keyword_map(tokens: set[str], keyword_map: dict[str, list[str]]) -> list[str]:
    matched: list[str] = []
    for tag, keywords in keyword_map.items():
        if any(keyword.lower() in tokens for keyword in keywords):
            matched.append(tag)
    return matched


def detect_vertical(tokens: set[str], rules: RoutingRules, source_text: str = "") -> str | None:
    phrase_text = " " + " ".join(TOKEN_RE.findall(source_text.lower())) + " "
    scored: list[tuple[int, int, str]] = []
    for name, vertical in rules.verticals.items():
        matches: set[str] = set()
        for keyword in vertical.all_keywords:
            parts = TOKEN_RE.findall(keyword)
            if not parts:
                continue
            if len(parts) == 1 and parts[0] in tokens:
                matches.add(keyword)
            elif len(parts) > 1 and f" {' '.join(parts)} " in phrase_text:
                matches.add(keyword)
        if matches:
            scored.append((-len(matches), vertical.priority, name))
    if not scored:
        return None
    scored.sort()
    return scored[0][2]


def _fuzzy_token_match(term: str, tokens: set[str]) -> str | None:
    if len(term) < 5:
        return None
    best_token = ""
    best_ratio = 0.0
    for token in tokens:
        if len(token) < 4 or token[0] != term[0] or abs(len(token) - len(term)) > 3:
            continue
        ratio = SequenceMatcher(None, term, token).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_token = token
    return best_token if best_ratio >= 0.8 else None


def detect_task_archetypes(
    tokens: set[str],
    rules: RoutingRules,
    source_text: str,
    explicit: str | None = None,
) -> tuple[list[ArchetypeCandidate], bool]:
    if explicit:
        if explicit not in rules.task_archetypes:
            raise ValueError(
                f"Unknown task_archetype '{explicit}'. Available: {', '.join(sorted(rules.task_archetypes))}"
            )
        return [ArchetypeCandidate(name=explicit, score=100, confidence=1.0, exact_phrases=["explicit"])], False
    phrase_text = " " + " ".join(TOKEN_RE.findall(source_text.lower())) + " "
    candidates: list[ArchetypeCandidate] = []
    for name, archetype in rules.task_archetypes.items():
        exact_phrases: list[str] = []
        exact_tokens: list[str] = []
        fuzzy_tokens: list[str] = []
        fuzzy_source_tokens: set[str] = set()
        score = 0
        for keyword in sorted(archetype.all_keywords):
            parts = TOKEN_RE.findall(keyword)
            if not parts:
                continue
            if len(parts) > 1 and f" {' '.join(parts)} " in phrase_text:
                exact_phrases.append(keyword)
                score += 12 + (2 * len(parts))
                continue
            if len(parts) != 1 or parts[0] in ARCHETYPE_GENERIC_TOKENS:
                continue
            term = parts[0]
            if term in tokens:
                exact_tokens.append(term)
                score += 4
                continue
            fuzzy = _fuzzy_token_match(term, tokens)
            if fuzzy and fuzzy not in fuzzy_source_tokens:
                fuzzy_source_tokens.add(fuzzy)
                fuzzy_tokens.append(f"{fuzzy}->{term}")
                score += 2
        evidence_count = len(exact_phrases) + len(exact_tokens) + len(fuzzy_tokens)
        if not exact_phrases and evidence_count < archetype.minimum_keyword_matches:
            continue
        confidence = min(0.98, 0.4 + (score / 20.0))
        if exact_phrases:
            confidence = max(confidence, 0.88)
        if fuzzy_tokens and not exact_phrases and not exact_tokens:
            confidence = min(confidence, 0.78)
        candidates.append(
            ArchetypeCandidate(
                name=name,
                score=score,
                confidence=round(confidence, 3),
                exact_phrases=exact_phrases,
                exact_tokens=exact_tokens,
                fuzzy_tokens=fuzzy_tokens,
            )
        )
    candidates.sort(key=lambda item: (-item.score, rules.task_archetypes[item.name].priority, item.name))
    ambiguous = False
    if len(candidates) > 1:
        top = candidates[0].score
        runner_up = candidates[1].score
        top_rule = rules.task_archetypes[candidates[0].name]
        runner_is_parent = candidates[1].name in top_rule.supersedes
        ambiguous = (
            not runner_is_parent
            and runner_up >= 4
            and (runner_up >= top * 0.78 or top - runner_up <= 2)
        )
    if ambiguous:
        candidates[0].confidence = round(candidates[0].confidence * 0.68, 3)
    return candidates[:5], ambiguous


def detect_task_archetype(
    tokens: set[str],
    rules: RoutingRules,
    source_text: str,
    explicit: str | None = None,
) -> tuple[str | None, float]:
    candidates, _ = detect_task_archetypes(tokens, rules, source_text, explicit)
    if not candidates:
        return None, 0.0
    return candidates[0].name, candidates[0].confidence


def detect_surface_kind(request: DesignContextRequest, tokens: set[str], task_archetype: str | None) -> str:
    if request.surface_kind:
        explicit = request.surface_kind.lower()
        if explicit not in SURFACE_KIND_ALIASES:
            raise ValueError(
                f"Unknown surface_kind '{request.surface_kind}'. Available: {', '.join(sorted(SURFACE_KIND_ALIASES))}"
            )
        return SURFACE_KIND_ALIASES[explicit]
    surface = request.surface.lower()
    layout = request.layout_mode.lower()
    if surface in {"app", "instrument", "game", "docs", "landing"}:
        return surface
    if task_archetype in {"arcade_game", "tactics_game", "game"}:
        return "game"
    if surface.startswith("app.") or layout in {"app", "dashboard", "workspace"}:
        return "app"
    if surface.startswith(STRUCTURED_LANDING_SURFACE_PREFIXES):
        return "landing"
    explicit_intent_tokens = tokenize(strip_inline_negative_clauses([request.task, *request.constraints]))
    if LANDING_INTENT_TOKENS.intersection(explicit_intent_tokens) and (
        surface.startswith("website") or layout in {"homepage", "landing", "hero"}
    ):
        return "landing"
    if task_archetype in {
        "settings",
        "kanban",
        "notifications",
        "file_manager",
        "calendar",
        "email_client",
        "code_playground",
        "editor",
        "database_tool",
        "spreadsheet",
        "timeline",
        "contacts",
        "learning_tool",
        "analytics_dashboard",
        "gradient_tool",
        "creative_image_tool",
        "arcade_game",
        "tactics_game",
        "game",
    }:
        return "game" if task_archetype in {"arcade_game", "tactics_game", "game"} else "app"
    if task_archetype == "interactive_instrument":
        return "instrument"
    if surface.startswith("website.docs") or task_archetype == "docs":
        return "docs"
    if {"app", "interface", "workspace", "editor", "dashboard", "console", "tool"}.intersection(tokens):
        return "app"
    if layout in {"homepage", "landing", "hero"} or surface.startswith("website"):
        return "landing"
    return "unknown"


def _preference_flags(tokens: set[str], rules: RoutingRules) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for pref, keywords in rules.preference_keywords.items():
        flags[pref] = bool(tokens.intersection({keyword.lower() for keyword in keywords}))
    return flags


def _collect_avoided_tags(tokens: set[str], rules: RoutingRules) -> tuple[set[str], set[str]]:
    avoided_motifs: set[str] = set()
    avoided_strengths: set[str] = set()
    for token, exclusion in rules.negative_style_exclusions.items():
        if token.lower() in tokens:
            avoided_motifs.update(exclusion.motif)
            avoided_strengths.update(exclusion.strength)
    return avoided_motifs, avoided_strengths


def _dedupe_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def normalize_request(request: DesignContextRequest, rules: RoutingRules | None = None) -> NormalizedRequest:
    rules = rules or load_routing_rules()
    semantic_constraints = [constraint for constraint in request.constraints if not PROOF_CONSTRAINT_RE.search(constraint)]
    semantic_parts = [request.surface, request.task, request.layout_mode, request.stack, *request.tone, *semantic_constraints]
    source_text = " ".join(strip_inline_negative_clauses(semantic_parts))
    positive = request_tokens(request, include_negative=True)
    negatives = negative_tokens(request)
    effective = positive.difference(negatives)
    task_archetype_candidates, task_archetype_ambiguous = detect_task_archetypes(
        effective,
        rules,
        source_text,
        explicit=request.task_archetype,
    )
    task_archetype = task_archetype_candidates[0].name if task_archetype_candidates else None
    task_archetype_confidence = task_archetype_candidates[0].confidence if task_archetype_candidates else 0.0
    surface_kind = detect_surface_kind(request, effective, task_archetype)
    if request.task_archetype is None and surface_kind == "game":
        task_archetype_candidates = [
            candidate
            for candidate in task_archetype_candidates
            if candidate.name in {"arcade_game", "tactics_game", "game"}
        ]
        task_archetype = task_archetype_candidates[0].name if task_archetype_candidates else "game"
        task_archetype_confidence = (
            task_archetype_candidates[0].confidence if task_archetype_candidates else 0.4
        )
        task_archetype_ambiguous = False

    motifs: list[str] = _tags_from_keyword_map(positive, rules.motif_keywords)
    strengths: list[str] = _tags_from_keyword_map(positive, rules.strength_keywords)
    if request.route_profile == "legacy_exploration":
        vertical_name = None
    elif surface_kind == "game" and "browser_game" in rules.verticals:
        vertical_name = "browser_game"
    else:
        vertical_name = detect_vertical(effective, rules, source_text)
    vertical = rules.verticals.get(vertical_name) if vertical_name else None
    if (
        request.task_archetype is None
        and surface_kind == "landing"
        and vertical is not None
        and task_archetype is not None
        and all(not candidate.exact_phrases for candidate in task_archetype_candidates)
    ):
        task_archetype = None
        task_archetype_confidence = 0.0
        task_archetype_ambiguous = False
    archetype_rule = rules.task_archetypes.get(task_archetype or "")
    if archetype_rule is not None:
        motifs.extend(archetype_rule.required_any_motifs)
    if (
        request.task_archetype is None
        and surface_kind == "landing"
        and vertical is not None
        and task_archetype_ambiguous
        and all(not candidate.exact_phrases for candidate in task_archetype_candidates)
    ):
        task_archetype_ambiguous = False
    if vertical is not None:
        motifs.extend(vertical.motif_tags)
        strengths.extend(vertical.strength_tags)

    preferences = _preference_flags(effective, rules)
    for pref, enabled in preferences.items():
        if not enabled:
            continue
        expansion = rules.preference_tag_expansions.get(pref)
        if expansion is None:
            continue
        motifs.extend(expansion.motif)
        strengths.extend(expansion.strength)

    if request.surface == "website.homepage_hero":
        motifs.append("hero_shell")
    if surface_kind == "landing":
        strengths.append("hero_treatment")
    elif surface_kind in {"app", "instrument"}:
        motifs.extend(["command_surface", "glass_panel", "dashboard_panel"])
        strengths.extend(["navigation_clarity", "section_sequencing"])
        if vertical_name is None and task_archetype == "analytics_dashboard":
            vertical_name = "saas_dashboard"
            vertical = rules.verticals.get(vertical_name)
            if vertical is not None:
                motifs.extend(vertical.motif_tags)
                strengths.extend(vertical.strength_tags)
    elif surface_kind == "game":
        motifs.extend(["gameplay_first", "interactive_stage"])
        strengths.extend(["navigation_clarity", "state_completeness", "interaction_feedback"])
    if "hero_shell" in motifs:
        strengths.append("headline_hierarchy")

    avoided_motifs, avoided_strengths = _collect_avoided_tags(negatives, rules)
    motifs = [tag for tag in motifs if tag not in avoided_motifs]
    strengths = [tag for tag in strengths if tag not in avoided_strengths]

    proof_tokens = tokenize([request.task, *request.constraints])
    requires_screenshot_fit = bool(
        {"screenshot", "viewport", "fold", "pixel", "fit"}.intersection(proof_tokens)
        or any("1512x812" in c or "390x844" in c for c in request.constraints)
    )

    dark_vertical = None
    if effective.intersection({"grading", "excavation", "earthworks", "earthwork", "sitework", "dirt"}):
        dark_vertical = "grading"
    elif effective.intersection({"roofing", "roofer", "roof", "shingle", "shingles"}):
        dark_vertical = "roofing"

    avoids_dark = "dark" in negatives
    # Dark industrial preference so null-vertical ties do not elect light beauty packs by budget.
    prefers_dark = (not avoids_dark) and bool(
        effective.intersection({"dark", "industrial", "garage", "showroom"})
        or any(t.lower() in {"dark", "industrial", "garage", "showroom"} for t in request.tone)
    )

    return NormalizedRequest(
        surface=request.surface,
        surface_kind=surface_kind,
        task_archetype=task_archetype,
        task_archetype_confidence=task_archetype_confidence,
        task_archetype_candidates=task_archetype_candidates,
        task_archetype_ambiguous=task_archetype_ambiguous,
        motif_tags=_dedupe_sorted(motifs),
        strength_tags=_dedupe_sorted(strengths),
        avoided_motif_tags=sorted(avoided_motifs),
        avoided_strength_tags=sorted(avoided_strengths),
        tone=list(request.tone),
        layout_mode=request.layout_mode,
        stack=request.stack,
        requires_screenshot_fit=requires_screenshot_fit,
        prefers_light_mode=preferences.get("light", False),
        prefers_warm_mode=preferences.get("warm", False),
        prefers_residential_mode=preferences.get("residential", False),
        prefers_editorial_mode=preferences.get("editorial", False),
        prefers_dark_mode=prefers_dark,
        avoids_dark_mode=avoids_dark,
        avoids_industrial_mode=bool({"industrial", "heavy", "equipment"}.intersection(negatives)),
        prefers_real_imagery=preferences.get("real_imagery", False),
        specialty_service_class=vertical_name,
        dark_service_vertical=dark_vertical,
    )
