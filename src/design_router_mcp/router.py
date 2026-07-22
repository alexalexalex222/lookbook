from __future__ import annotations

import logging
import hashlib
import json
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .atom_selector import select_shared_atoms
from .hybrid_retrieval import HybridRetriever
from .index_store import PackIndexRecord, RepositoryIndex, build_repository_index
from .lazy_loader import PackStore, load_shared_atoms
from .local_reranker import rerank_candidates
from .normalizer import normalize_request, request_tokens
from .rules import RoutingRules, load_routing_rules
from .sanitizer import scan_source_hygiene
from .schemas import (
    AtomSnippet,
    CodeFile,
    DesignContextRequest,
    ExampleSelection,
    LoadedPack,
    OptionalPattern,
    PackManifest,
    PatternCatalogEntry,
    RouteResolution,
    ScoreBreakdown,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ScoredRecord:
    record: PackIndexRecord
    score: ScoreBreakdown


@dataclass(frozen=True)
class _OptionalExampleCandidate:
    record: PackIndexRecord
    example_id: str
    score: int
    ux_roles: tuple[str, ...]
    matched_terms: tuple[str, ...]
    strength_tags: tuple[str, ...]
    motif_tags: tuple[str, ...]
    score_axes: tuple[tuple[str, int], ...]
    domain_fit: str
    mechanic_fit: int
    quality_score: int
    identity_risk: str


_GENERIC_PATTERN_ROLES = {
    "data_table",
    "filter_toolbar",
    "footer_full",
    "header_sticky",
    "navigation_shell",
}

_DOMAIN_TOKEN_GROUPS: dict[str, set[str]] = {
    "combat_sports": {"fight", "gym", "mma", "boxing", "grappling", "martial", "academy"},
    "plumbing": {"plumbing", "plumber", "pipe", "harborpipe", "stillwater", "drain", "sewer"},
    "roofing": {"roofing", "roof", "ridgecap", "summitline", "gullwing"},
    "moving": {"moving", "mover", "cresthaul"},
    "flooring": {"flooring", "floor", "copperbeam"},
    "cabinetry": {"cabinet", "cabinets", "cabinetry", "oakline"},
    "landscape": {"landscape", "landscaping", "ecoscapes", "mosswood", "ashgrove", "terraverde"},
    "dental": {"dental", "dentist", "cedarbrook", "quayside", "willowbend", "rivergate"},
    "beauty": {"medspa", "spa", "wax", "wellness", "lumena", "aurelia", "velvet"},
    "law": {"law", "legal", "llp", "hale", "winslow", "foster", "quinn"},
    "hvac": {"hvac", "heating", "thermaline", "air"},
    "garage_door": {"garage", "axlecraft"},
    "storage": {"storage", "stackpoint"},
    "construction": {"construction", "beaconframe"},
    "electrical": {"electric", "electrical", "voltway"},
    "fencing": {"fence", "gatewood"},
    "aerospace_launch": {"aerospace", "orbital", "launch", "mission"},
    "developer_docs": {"developer", "docs", "quickstart", "sdk"},
    "fintech_terminal": {"fintech", "markets", "trading"},
    "interactive_instrument": {"instrument", "synth", "sequencer"},
    "luxury_maison": {"luxury", "maison", "fragrance"},
    "reference_product": {"reference", "spec"},
    "browser_game": {
        "arcade",
        "apex",
        "racer",
        "race",
        "dungeon",
        "tactics",
        "neon",
        "roguelike",
        "chess",
        "sudoku",
        "solitaire",
        "breakout",
        "tower",
        "defense",
        "boids",
    },
}

_PRIORITY_ROLE_PRESETS: dict[str, tuple[str, ...]] = {
    "combat_sports": (
        "schedule_grid",
        "form_intake",
        "service_lane_set",
    ),
    "plumbing": (
        "phone_priority_layout",
        "coverage_signal",
        "service_area_signal",
        "form_intake",
        "process_steps",
        "proof_rail",
        "trust_rail",
    ),
    "arcade_game": (
        "gameplay_stage",
        "hud_cluster",
        "overlay_state",
        "responsive_control_dock",
        "control_cluster",
        "inventory_panel",
    ),
    "tactics_game": (
        "gameplay_stage",
        "hud_cluster",
        "control_cluster",
        "event_log",
        "overlay_state",
        "inventory_panel",
        "responsive_control_dock",
    ),
    "browser_game": (
        "gameplay_stage",
        "hud_cluster",
        "overlay_state",
        "control_cluster",
        "responsive_control_dock",
    ),
}

_GAME_UX_ROLES = {
    "gameplay_stage",
    "hud_cluster",
    "overlay_state",
    "inventory_panel",
    "control_cluster",
    "event_log",
    "responsive_control_dock",
    "stats_strip",
    "modal_flow",
}

_UX_ROLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "form_intake": (
        "trial request",
        "estimate request",
        "service request",
        "request form",
        "booking form",
        "inquiry form",
        "assessment",
        "intake",
        "form",
        "inquiry",
    ),
    "schedule_grid": ("schedule", "weekly schedule", "calendar", "class times", "classes", "timetable"),
    "proof_rail": ("proof", "results", "before", "after", "case study", "evidence", "portfolio"),
    "service_lane_set": (
        "services",
        "service paths",
        "program",
        "programs",
        "pathways",
        "offerings",
        "capabilities",
        "treatments",
    ),
    "process_steps": ("process", "method", "sequence", "steps", "progression", "timeline", "onboarding", "first visit"),
    "coverage_signal": ("service area", "coverage", "near you", "territory", "availability"),
    "consultation_flow": ("consultation", "booking", "discovery", "appointment"),
    "phone_priority_layout": ("phone", "call", "tel:"),
    "footer_full": ("footer", "contact"),
    "header_sticky": ("sticky header", "sticky nav", "persistent navigation"),
    "trust_rail": ("testimonial", "trusted", "review", "trust", "credible", "credentials", "proof safe"),
    "stats_strip": ("stats", "metrics", "kpi", "score", "timer"),
    "service_area_signal": (
        "service area",
        "areas served",
        "service coverage",
        "coverage flow",
        "coverage map",
        "territory",
    ),
    "navigation_shell": (
        "navigation",
        "mobile navigation",
        "sidebar",
        "side nav",
        "menu",
        "tabs",
        "breadcrumb",
        "file manager",
        "folder tree",
    ),
    "filter_toolbar": ("filter", "sort", "search", "toolbar"),
    "data_table": ("table", "rows", "columns", "ledger", "manifest", "roster"),
    "modal_flow": ("modal", "dialog", "drawer", "sheet"),
    "hud_cluster": ("hud", "speedometer", "lap position", "turn order", "party status", "vitals"),
    "overlay_state": ("overlay", "pause", "paused", "victory", "defeat", "game over", "reward modal", "restart flow"),
    "inventory_panel": ("inventory", "gear", "loadout", "garage", "upgrade", "items"),
    "control_cluster": (
        "controls",
        "control cluster",
        "command surface",
        "actions",
        "skill actions",
        "steering",
        "number pad",
        "command palette",
    ),
    "gameplay_stage": (
        "gameplay",
        "gameplay first",
        "interactive stage",
        "single screen stage",
        "playfield",
        "track",
        "dungeon",
        "tactical grid",
        "grid board",
        "board",
        "arena",
        "canvas stage",
        "arcade game",
        "racer",
        "roguelike",
        "tower defense",
        "solitaire",
        "sudoku",
        "chess",
        "breakout",
    ),
    "event_log": ("combat log", "event log", "activity log"),
    "responsive_control_dock": ("touch controls", "touch control", "mobile controls", "control dock", "thumb controls"),
}

_PATTERN_TERM_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "racing": ("racer", "race", "lap", "checkpoint", "driving", "hud"),
    "racer": ("race", "lap", "checkpoint", "driving", "hud"),
    "tactics": ("roguelike", "tower-defense", "chess", "grid", "turn", "combat"),
    "dungeon": ("roguelike", "inventory", "party", "combat", "map"),
    "plumbing": ("plumbing", "pipe", "water", "drain", "diagnostic"),
    "martial": ("fight", "gym", "combat", "training", "schedule"),
    "schedule": ("calendar", "timetable"),
    "contact": ("contacts", "phone", "form"),
    "analytics": ("dashboard", "stats", "chart", "table", "metrics"),
    "settings": ("preferences", "configuration", "toggle", "sidebar"),
    "notifications": ("alerts", "inbox", "unread", "feed"),
}

_ARCHETYPE_PATTERN_EXAMPLE_HINTS: dict[str, tuple[str, ...]] = {
    "arcade_game": ("racer", "breakout", "physics-sandbox", "boids"),
    "tactics_game": ("roguelike", "tower-defense", "chess", "sudoku", "solitaire"),
    "settings": ("settings",),
    "kanban": ("kanban-board",),
    "notifications": ("notifications",),
    "calendar": ("calendar", "gantt", "calendar-heatmap"),
    "code_playground": ("code-playground", "code-editor", "terminal"),
    "image_editor": ("image-cropper", "pixel-editor", "duotone"),
    "gradient_generator": ("gradient-studio", "gradient-generator"),
    "file_manager": ("file-manager", "browser-os"),
}

_PATTERN_JOB_BY_ROLE = {
    "form_intake": "Collect the minimum information needed for a clear next step.",
    "schedule_grid": "Make recurring times or availability easy to scan and choose.",
    "proof_rail": "Present compact, verifiable evidence without inventing claims.",
    "service_lane_set": "Organize programs, services, or capabilities by user intent.",
    "process_steps": "Explain the sequence from entry point to completion.",
    "coverage_signal": "Show availability or service coverage without map clutter.",
    "consultation_flow": "Reduce friction from interest to a scheduled consultation.",
    "phone_priority_layout": "Keep the phone path visible without overpowering the page.",
    "footer_full": "Close the page with complete navigation and contact structure.",
    "header_sticky": "Keep primary navigation accessible without covering content.",
    "trust_rail": "Place trust signals where they support a decision.",
    "stats_strip": "Surface a compact set of meaningful state or performance values.",
    "service_area_signal": "Clarify geographic fit and availability.",
    "navigation_shell": "Provide a stable orientation and navigation framework.",
    "filter_toolbar": "Let users narrow or reorganize a dense information set.",
    "data_table": "Make structured records scannable and comparable.",
    "modal_flow": "Handle a focused decision without losing the underlying context.",
    "hud_cluster": "Keep critical live state readable around the primary playfield.",
    "overlay_state": "Represent pause, completion, failure, or reward as explicit states.",
    "inventory_panel": "Organize selectable equipment, items, or upgrades.",
    "control_cluster": "Group high-frequency actions into a stable control surface.",
    "gameplay_stage": "Let the playable board or canvas own the primary viewport.",
    "event_log": "Expose recent system or combat events in a compact history.",
    "responsive_control_dock": "Keep touch controls reachable and clear of live state.",
}


def _tokens_from_text(value: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _infer_ux_roles_from_text(value: str) -> set[str]:
    text = " ".join(_ordered_phrase(value).split())
    tokens = set(text.split())
    roles: set[str] = set()
    for role, phrases in _UX_ROLE_KEYWORDS.items():
        for phrase in phrases:
            normalized = _ordered_phrase(phrase)
            if not normalized:
                continue
            if " " in normalized:
                matched = f" {normalized} " in f" {text} "
            else:
                matched = normalized in tokens
            if matched:
                roles.add(role)
                break
    return roles


def _infer_pattern_domains(tokens: set[str]) -> set[str]:
    return {
        domain
        for domain, domain_tokens in _DOMAIN_TOKEN_GROUPS.items()
        if tokens.intersection(domain_tokens)
    }


def _manifest_tokens(manifest: PackManifest) -> set[str]:
    parts: list[str] = [
        manifest.pack_id,
        manifest.family,
        *manifest.stack,
        *manifest.tones,
        *manifest.surfaces,
        *manifest.motif_tags,
        *manifest.supports_tasks,
        *manifest.origin_example_ids,
    ]
    return _tokens_from_text(" ".join(parts).replace("_", " ").replace("-", " "))


_GENERIC_ROUTE_TOKENS = {
    "a",
    "an",
    "and",
    "app",
    "as",
    "at",
    "be",
    "build",
    "by",
    "css",
    "design",
    "existing",
    "for",
    "from",
    "full",
    "html",
    "in",
    "interface",
    "is",
    "it",
    "of",
    "on",
    "or",
    "page",
    "professional",
    "screen",
    "site",
    "that",
    "the",
    "this",
    "to",
    "tool",
    "upgrade",
    "user",
    "website",
    "where",
    "with",
}

_APP_FAMILIES = {
    "website.developer_tool",
    "website.docs",
    "website.editorial_analytics",
    "website.fintech_terminal",
    "website.interactive_experience",
    "website.productivity_app",
    "website.saas_dashboard",
}
_GAME_FAMILIES = {"website.game"}
_INSTRUMENT_FAMILIES = {"website.interactive_experience"}
_LANDING_SURFACES = {"homepage", "hero", "landing"}

_SIGNATURE_GENERIC_TOKENS = _GENERIC_ROUTE_TOKENS.difference({"css", "html"})


def _ordered_phrase(value: str) -> str:
    import re

    return " ".join(re.findall(r"[a-z0-9]+", value.lower().replace("_", " ").replace("-", " ")))


def request_tokens_for_compatibility(request: DesignContextRequest) -> set[str]:
    return request_tokens(request).difference(_GENERIC_ROUTE_TOKENS | {"screenshot", "viewport", "mobile", "desktop"})


def weights_for_gate(rules: RoutingRules) -> int:
    return max(12, rules.weights.get("task_token_overlap", 7) * 2)


def _route_trace_id(
    request: DesignContextRequest,
    *,
    rules_version: str,
) -> str:
    payload = {
        "request": request.model_dump(mode="json"),
        "rules_version": rules_version,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()[:16]


def _candidate_label(item: _ScoredRecord) -> str:
    origins = item.record.manifest.origin_example_ids
    value = origins[0] if origins else item.record.manifest.pack_id
    return value.replace("_", " ").replace("-", " ")


def route_confidence(
    ranked: list[_ScoredRecord],
    normalized: Any | None = None,
    request: DesignContextRequest | None = None,
    rules: RoutingRules | None = None,
) -> dict[str, Any]:
    if not ranked:
        return {
            "value": 0.0,
            "level": "none",
            "margin": 0,
            "decision": "clarify",
            "needs_clarification": True,
            "reasons": ["no anchor candidates"],
            "clarification_question": "What primary workflow should this interface support?",
        }
    top = ranked[0].score.total
    runner_up = ranked[1].score.total if len(ranked) > 1 else 0
    margin = max(0, top - runner_up)
    top_score = ranked[0].score
    informative_tokens = request_tokens_for_compatibility(request) if request is not None else set()
    margin_signal = min(1.0, margin / 45.0)
    task_signal = min(1.0, max(0, top_score.task_fit) / 90.0)
    lexical_matches = set(top_score.matched_terms.get("task", []))
    lexical_matches.update(top_score.matched_terms.get("pack_signature", []))
    lexical_matches.update(top_score.matched_terms.get("request_pack_tokens", []))
    lexical_signal = min(1.0, len(lexical_matches) / 5.0)
    specificity_signal = min(1.0, len(informative_tokens) / 8.0)
    archetype_signal = float(getattr(normalized, "task_archetype_confidence", 0.0) or 0.0)
    if not archetype_signal and getattr(normalized, "specialty_service_class", None):
        archetype_signal = 0.75
    value = (
        0.28 * margin_signal
        + 0.27 * task_signal
        + 0.18 * lexical_signal
        + 0.15 * specificity_signal
        + 0.12 * archetype_signal
    )
    reasons: list[str] = []
    ambiguous = bool(getattr(normalized, "task_archetype_ambiguous", False))
    forced_clarify = False
    if ambiguous:
        value *= 0.55
        reasons.append("multiple task archetypes have comparable evidence")
        forced_clarify = True
    archetype_name = getattr(normalized, "task_archetype", None)
    archetype = rules.task_archetypes.get(archetype_name or "") if rules is not None else None
    if archetype is not None and archetype.clarify_without_signature and top_score.signature_fit == 0:
        value = min(value, 0.44)
        forced_clarify = True
        reasons.append("brief names a broad workflow but not a distinguishing variant")
    if not getattr(normalized, "task_archetype", None) and not getattr(normalized, "specialty_service_class", None):
        if request is not None and (
            request.surface == "website.local_service"
            or {"local", "service"}.issubset(informative_tokens)
        ):
            value = min(value, 0.35)
            forced_clarify = True
            reasons.append("local-service brief does not identify the service vertical")
        if len(informative_tokens) <= 3:
            value = min(value, 0.3)
            reasons.append("brief is too sparse to identify a workflow or vertical")
        elif top_score.task_fit < 24:
            value = min(value, 0.48)
            reasons.append("no task archetype or vertical has enough evidence")
    if margin < 12:
        reasons.append("top anchors are closely matched")
    if top_score.task_fit < 28:
        reasons.append("selected anchor has weak task-specific evidence")

    value = round(min(1.0, max(0.0, value)), 3)
    needs_clarification = forced_clarify or value < 0.5
    decision = "clarify" if needs_clarification else "route_with_caution" if value < 0.72 else "route"
    level = "high" if value >= 0.72 else "medium" if value >= 0.5 else "low"
    options: list[str] = []
    archetype_candidates = list(getattr(normalized, "task_archetype_candidates", []) or [])
    if ambiguous and archetype_candidates:
        options = [candidate.name.replace("_", " ") for candidate in archetype_candidates[:3]]
    elif archetype is not None and archetype.preferred_pack_ids:
        preferred = [
            item for item in ranked if item.record.manifest.pack_id in archetype.preferred_pack_ids
        ]
        options = [_candidate_label(item) for item in preferred[:3]]
    elif len(ranked) > 1 and getattr(normalized, "task_archetype", None):
        options = [_candidate_label(item) for item in ranked[:3]]
    question = ""
    if needs_clarification:
        if request is not None and (
            request.surface == "website.local_service"
            or {"local", "service"}.issubset(informative_tokens)
        ):
            question = "What service vertical is this for, such as plumbing, roofing, dental, landscaping, or another trade?"
            options = []
        elif options:
            question = f"Which direction is primary: {', '.join(options)}?"
        else:
            question = "What primary workflow or industry should this design support?"
    return {
        "value": value,
        "level": level,
        "margin": margin,
        "decision": decision,
        "needs_clarification": needs_clarification,
        "reasons": reasons,
        "clarification_question": question,
        "clarification_options": options,
        "signals": {
            "margin": round(margin_signal, 3),
            "task": round(task_signal, 3),
            "lexical": round(lexical_signal, 3),
            "specificity": round(specificity_signal, 3),
            "archetype": round(archetype_signal, 3),
        },
    }


class DesignRouter:
    """Data-driven anchor/support router.

    The router can be constructed from either a RepositoryIndex (preferred) or
    the original LoadedPack list (compatibility). Routing uses only manifest
    metadata until the final selected packs/examples are hydrated by PackStore.
    """

    def __init__(
        self,
        packs_or_index: list[LoadedPack] | RepositoryIndex,
        shared_atoms: list[AtomSnippet] | None = None,
        *,
        repo_root: Path | str | None = None,
        rules: RoutingRules | None = None,
        store: PackStore | None = None,
    ) -> None:
        self.rules = rules or load_routing_rules(Path(repo_root).expanduser().resolve() if repo_root else None)
        self.shared_atoms = shared_atoms or []
        if isinstance(packs_or_index, RepositoryIndex):
            self.index = packs_or_index
            self.repo_root = self.index.repo_root
            self._legacy_packs: dict[str, LoadedPack] = {}
        else:
            root = Path(repo_root).expanduser().resolve() if repo_root else self._infer_repo_root(packs_or_index)
            records = []
            self._legacy_packs = {pack.manifest.pack_id: pack for pack in packs_or_index}
            for pack in packs_or_index:
                manifest_path = pack.pack_dir / "manifest.json"
                mtime = manifest_path.stat().st_mtime_ns if manifest_path.exists() else 0
                records.append(PackIndexRecord(pack.manifest, pack.pack_dir, manifest_path, mtime))
            self.index = RepositoryIndex(root, records)
            self.repo_root = root
        self.store = store or PackStore(self.repo_root, self.index)
        self.hybrid_retriever = HybridRetriever(self.repo_root, self.index.anchors)
        if not self.shared_atoms:
            self.shared_atoms = load_shared_atoms(self.repo_root)

    @classmethod
    def from_repo(cls, repo_root: Path | str, *, refresh_index: bool = False, rules_path: Path | str | None = None) -> "DesignRouter":
        root = Path(repo_root).expanduser().resolve()
        rules = load_routing_rules(root, rules_path)
        index = build_repository_index(root, refresh=refresh_index)
        store = PackStore(root, index)
        return cls(index, load_shared_atoms(root), repo_root=root, rules=rules, store=store)

    @staticmethod
    def _infer_repo_root(packs: list[LoadedPack]) -> Path:
        if not packs:
            return Path.cwd()
        pack_dir = packs[0].pack_dir.resolve()
        parts = list(pack_dir.parts)
        if "goldensets" in parts:
            idx = parts.index("goldensets")
            return Path(*parts[:idx]) if idx else Path("/")
        return pack_dir.parent

    @property
    def packs(self) -> list[LoadedPack]:
        if self._legacy_packs:
            return list(self._legacy_packs.values())
        return [self.store.get_pack(record.manifest.pack_id, include_full=False, max_code_chars=1600) for record in self.index.records]

    def _task_fit(self, request: DesignContextRequest, manifest: PackManifest) -> tuple[int, list[str]]:
        weights = self.rules.weights
        task_text = _ordered_phrase(request.task)
        task_tokens = _tokens_from_text(task_text).difference(_GENERIC_ROUTE_TOKENS)
        task_words = task_text.split()
        task_bigrams = set(zip(task_words, task_words[1:]))
        best_score = 0
        best_matches: list[str] = []
        for candidate in manifest.supports_tasks:
            candidate_text = _ordered_phrase(candidate)
            candidate_tokens = _tokens_from_text(candidate_text).difference(_GENERIC_ROUTE_TOKENS)
            overlap = sorted(task_tokens.intersection(candidate_tokens))
            score = min(28, len(overlap) * weights.get("task_token_overlap", 7))
            candidate_words = candidate_text.split()
            candidate_bigrams = set(zip(candidate_words, candidate_words[1:]))
            bigram_overlap = task_bigrams.intersection(candidate_bigrams)
            score += min(30, len(bigram_overlap) * weights.get("task_bigram_overlap", 15))
            if candidate_text and (f" {candidate_text} " in f" {task_text} " or f" {task_text} " in f" {candidate_text} "):
                score += weights.get("task_exact_phrase", 40)
            if score > best_score:
                best_score = score
                best_matches = overlap
        return best_score, best_matches

    def _pack_signature_fit(self, request: DesignContextRequest, signatures: list[str]) -> tuple[int, list[str]]:
        if not signatures:
            return 0, []
        task_text = _ordered_phrase(request.task)
        task_tokens = _tokens_from_text(task_text).difference(_GENERIC_ROUTE_TOKENS)
        matches: list[str] = []
        score = 0
        for signature in signatures:
            signature_text = _ordered_phrase(signature)
            parts = [part for part in signature_text.split() if part not in _SIGNATURE_GENERIC_TOKENS]
            if not parts:
                continue
            if len(parts) > 1 and f" {signature_text} " in f" {task_text} ":
                matches.append(signature)
                score += 28 + min(12, len(parts) * 3)
                continue
            exact = [part for part in parts if part in task_tokens]
            fuzzy: list[str] = []
            for part in parts:
                if part in task_tokens or len(part) < 5:
                    continue
                best = max((SequenceMatcher(None, part, token).ratio() for token in task_tokens), default=0.0)
                if best >= 0.82:
                    fuzzy.append(part)
            coverage = (len(exact) + len(fuzzy)) / len(parts)
            if coverage >= 1.0:
                matches.append(signature)
                score += 16 + (4 * len(exact)) + (2 * len(fuzzy))
            elif coverage >= 0.6 and len(parts) > 1:
                matches.append(signature)
                score += 8 + (3 * len(exact)) + len(fuzzy)
        return min(80, score), matches

    def _anti_pattern_penalty(self, request: DesignContextRequest, manifest: PackManifest) -> tuple[int, list[str]]:
        request_tokens = request_tokens_for_compatibility(request)
        positive_manifest_tokens = _tokens_from_text(
            " ".join([manifest.pack_id, *manifest.supports_tasks, *manifest.motif_tags])
            .replace("_", " ")
            .replace("-", " ")
        )
        best_hits: list[str] = []
        for anti_pattern in manifest.anti_patterns:
            anti_tokens = _tokens_from_text(anti_pattern).difference(_GENERIC_ROUTE_TOKENS | positive_manifest_tokens)
            hits = sorted(request_tokens.intersection(anti_tokens))
            if len(hits) > len(best_hits):
                best_hits = hits
        if len(best_hits) < 2:
            return 0, []
        penalty = max(-24, len(best_hits) * self.rules.weights.get("anti_pattern_token", -8))
        return int(penalty), best_hits

    def _score_record(self, request: DesignContextRequest, normalized, record: PackIndexRecord) -> ScoreBreakdown:
        manifest = record.manifest
        weights = self.rules.weights
        manifest_tokens = _manifest_tokens(manifest)
        tokens = request_tokens(request)
        vertical_name = normalized.specialty_service_class
        vertical = self.rules.verticals.get(vertical_name) if vertical_name else None
        archetype = self.rules.task_archetypes.get(normalized.task_archetype or "")

        surface = 0
        if request.surface == manifest.family:
            surface = weights.get("surface_exact", 30)
        elif request.surface.startswith("website") and manifest.family.startswith("website"):
            surface = weights.get("surface_family", 14)
        family_fit = 0
        if normalized.surface_kind == "game":
            family_fit = (
                weights.get("surface_kind_family", 20)
                if manifest.family in _GAME_FAMILIES
                else weights.get("surface_kind_mismatch", -35)
            )
        elif normalized.surface_kind == "instrument":
            family_fit = (
                weights.get("surface_kind_family", 20)
                if manifest.family in _INSTRUMENT_FAMILIES
                else weights.get("surface_kind_mismatch", -35)
            )
        elif normalized.surface_kind == "app":
            family_fit = (
                weights.get("surface_kind_family", 20)
                if manifest.family in _APP_FAMILIES
                else weights.get("surface_kind_mismatch", -35)
            )
        elif normalized.surface_kind in {"landing", "docs"} and manifest.family.startswith("website"):
            family_fit = weights.get("surface_family", 14)

        motif_overlap = sorted(set(normalized.motif_tags).intersection(manifest.motif_tags))
        motif = min(24, len(motif_overlap) * weights.get("motif", 4))

        strength_overlap = sorted(set(normalized.strength_tags).intersection(set(manifest.motif_tags + manifest.supports_tasks + manifest.tones)))
        strength_bonus = min(12, len(strength_overlap) * weights.get("strength", 3))
        motif += strength_bonus

        stack = weights.get("stack", 10) if request.stack == "unknown" or request.stack in manifest.stack else 0
        tone_overlap = sorted(set(request.tone).intersection(manifest.tones))
        tone = min(18, len(tone_overlap) * weights.get("tone", 5))
        layout = weights.get("layout", 10) if request.layout_mode in manifest.surfaces else 0
        # Screenshot availability is a quality/proof signal, never semantic relevance.
        screenshot_fit = 0
        confidence = manifest.confidence_score * weights.get("confidence", 1)
        task_fit, task_matches = self._task_fit(request, manifest)
        anti_pattern, anti_pattern_matches = self._anti_pattern_penalty(request, manifest)
        signature_fit = 0
        signature_matches: list[str] = []
        archetype_matches: list[str] = []
        if archetype is not None:
            signature_fit, signature_matches = self._pack_signature_fit(
                request,
                archetype.pack_signatures.get(manifest.pack_id, []),
            )
            task_fit += signature_fit
            if manifest.family in archetype.preferred_families:
                task_fit += weights.get("task_archetype_family", 18)
                archetype_matches.append(f"family:{manifest.family}")
            pack_bonus = archetype.preferred_pack_ids.get(manifest.pack_id, 0)
            if pack_bonus:
                if len(archetype.preferred_pack_ids) == 1 or signature_fit > 0:
                    task_fit += pack_bonus
                    archetype_matches.append(f"pack:{manifest.pack_id}")
                else:
                    task_fit += min(6, max(0, pack_bonus // 6))
            required_overlap = sorted(set(archetype.required_any_motifs).intersection(manifest.motif_tags))
            if required_overlap:
                task_fit += min(16, len(required_overlap) * 8)
                archetype_matches.extend(f"motif:{item}" for item in required_overlap)
            if normalized.surface_kind != "landing" and manifest.family in archetype.blocked_families:
                family_fit -= 80

        request_bias = 0
        vertical_matches: list[str] = []
        if vertical is not None:
            vertical_matches = sorted(manifest_tokens.intersection(vertical.all_keywords))
            request_bias += min(15, len(vertical_matches) * weights.get("vertical_pack_token", 3))
            request_bias += sum(weights.get("vertical_tone", 2) for tone_name in vertical.prefer_tones if tone_name in manifest.tones)
            request_bias += vertical.preferred_anchor_pack_ids.get(manifest.pack_id, 0)
            request_bias += vertical.penalized_anchor_pack_ids.get(manifest.pack_id, 0)

        if normalized.prefers_light_mode and ("light" in manifest.tones or "light_precision" in manifest.motif_tags):
            request_bias += 5
        if normalized.prefers_warm_mode and ("warm" in manifest.tones or "craftsmanship" in manifest.tones):
            request_bias += 5
        if normalized.prefers_residential_mode and "residential" in manifest.tones:
            request_bias += 5
        if normalized.prefers_editorial_mode and "editorial" in manifest.tones:
            request_bias += 5
        if normalized.prefers_dark_mode:
            if "dark" in manifest.tones or "dark_texture" in manifest.motif_tags:
                request_bias += 5
            if "light" in manifest.tones and "beauty" in manifest.tones:
                request_bias -= 12
            if manifest.pack_id in {"velvet_fig_beauty_editorial_v1", "aurelia_medspa_editorial_v1"}:
                request_bias -= 12
        if normalized.avoids_dark_mode and ("dark" in manifest.tones or "dark_texture" in manifest.motif_tags):
            request_bias -= 12
        if normalized.avoids_industrial_mode and ("industrial" in manifest.tones or "industrial_frame" in manifest.motif_tags):
            request_bias -= 12

        dashboard_request = normalized.surface_kind in {"app", "instrument"} or normalized.layout_mode == "dashboard"
        if dashboard_request:
            dashboard_motifs = {"command_surface", "glass_panel", "dashboard_panel", "tabs_panel"}
            if dashboard_motifs.intersection(manifest.motif_tags):
                request_bias += 20
            if manifest.pack_id in {
                "emberforge_fight_gym_black_red_v1",
                "iron_circuit_fight_academy_black_copper_v1",
                "holland_dirt_black_yellow_v1",
            }:
                request_bias -= 45
            if "hero_shell" in manifest.motif_tags and not dashboard_motifs.intersection(manifest.motif_tags):
                request_bias -= 15

        if archetype is not None and normalized.task_archetype_confidence >= 0.75:
            request_bias = max(-20, min(20, request_bias))

        direct_pack_overlap = sorted(tokens.intersection(manifest_tokens).difference(_GENERIC_ROUTE_TOKENS | {"local", "service", "homepage", "landing"}))
        request_bias += min(9, len(direct_pack_overlap) * 3)

        total = surface + family_fit + motif + stack + tone + layout + screenshot_fit + task_fit + anti_pattern + request_bias + confidence
        return ScoreBreakdown(
            pack_id=manifest.pack_id,
            role=manifest.role,
            total=int(total),
            surface=int(surface),
            motif=int(motif),
            stack=int(stack),
            tone=int(tone),
            layout=int(layout),
            screenshot_fit=int(screenshot_fit),
            task_fit=int(task_fit),
            signature_fit=int(signature_fit),
            retrieval_fit=0,
            family_fit=int(family_fit),
            anti_pattern=int(anti_pattern),
            request_bias=int(request_bias),
            confidence=int(confidence),
            matched_terms={
                "motif": motif_overlap,
                "strength": strength_overlap,
                "tone": tone_overlap,
                "vertical": vertical_matches,
                "task": task_matches,
                "pack_signature": signature_matches,
                "task_archetype": archetype_matches,
                "anti_pattern": anti_pattern_matches,
                "screenshot_available": ["yes"] if manifest.screenshot_paths else [],
                "request_pack_tokens": direct_pack_overlap,
            },
        )

    def _pick_anchor(self, request: DesignContextRequest, normalized) -> _ScoredRecord:
        return self._rank_anchors(request, normalized)[0]

    def _rank_anchors_with_meta(self, request: DesignContextRequest, normalized) -> tuple[list[_ScoredRecord], dict[str, Any]]:
        candidates = [_ScoredRecord(record, self._score_record(request, normalized, record)) for record in self.index.anchors]
        if not candidates:
            raise ValueError("No anchor packs are available. Expected at least one goldensets/**/manifest.json with role='anchor'.")
        initial_count = len(candidates)
        surface_candidates = candidates
        if normalized.surface_kind == "game":
            gated = [item for item in candidates if item.record.manifest.family in _GAME_FAMILIES]
            if gated:
                surface_candidates = gated
        elif normalized.surface_kind == "instrument":
            gated = [item for item in candidates if item.record.manifest.family in _INSTRUMENT_FAMILIES]
            if gated:
                surface_candidates = gated
        elif normalized.surface_kind == "app":
            gated = [item for item in candidates if item.record.manifest.family in _APP_FAMILIES]
            if gated:
                surface_candidates = gated
        elif normalized.surface_kind == "landing":
            gated = [
                item
                for item in candidates
                if _LANDING_SURFACES.intersection(item.record.manifest.surfaces)
            ]
            if gated:
                surface_candidates = gated
        elif normalized.surface_kind == "docs":
            gated = [item for item in candidates if item.record.manifest.family == "website.docs"]
            if gated:
                surface_candidates = gated

        archetype_candidates = surface_candidates
        archetype = self.rules.task_archetypes.get(normalized.task_archetype or "")
        if (
            archetype is not None
            and normalized.task_archetype_confidence >= 0.6
            and not normalized.task_archetype_ambiguous
            and normalized.surface_kind != "landing"
        ):
            gated = [
                item
                for item in surface_candidates
                if item.record.manifest.pack_id in archetype.preferred_pack_ids
                or (
                    item.record.manifest.family in archetype.preferred_families
                    and (
                        item.score.task_fit > weights_for_gate(self.rules)
                        or bool(set(archetype.required_any_motifs).intersection(item.record.manifest.motif_tags))
                    )
                )
            ]
            if gated:
                archetype_candidates = gated

        candidates = archetype_candidates
        candidates.sort(key=lambda item: (-item.score.total, item.record.manifest.token_budget_hint, item.record.manifest.pack_id))
        baseline_winner = candidates[0].record.manifest.pack_id
        hybrid_meta: dict[str, Any] = {
            "profile": request.route_profile,
            "active": request.route_profile in {"hybrid_v4", "hybrid_v5"},
            "shadow": request.route_profile == "hybrid_shadow_v1",
            "baseline_winner": baseline_winner,
            "health": self.hybrid_retriever.health(),
        }
        local_rerank_meta: dict[str, Any] = {
            "mode": request.rerank_mode,
            "available": False,
            "valid": False,
            "promote": False,
            "winner": baseline_winner,
            "reason_code": "profile_not_v5",
        }
        if request.route_profile in {"hybrid_v4", "hybrid_shadow_v1", "hybrid_v5"}:
            hybrid_results = self.hybrid_retriever.rank(
                request,
                [item.record for item in candidates],
                rules_rank=[item.record.manifest.pack_id for item in candidates],
                include_pixel=request.route_profile == "hybrid_v5",
                query_expansions=[
                    value
                    for candidate in normalized.task_archetype_candidates[:3]
                    for value in [
                        candidate.name.replace("_", " "),
                        *candidate.exact_phrases,
                        *candidate.exact_tokens,
                        *(item.split("->", 1)[-1] for item in candidate.fuzzy_tokens),
                    ]
                ],
            )
            by_id = {result.pack_id: result for result in hybrid_results}
            hybrid_meta["top"] = [
                {
                    "pack_id": result.pack_id,
                    "fused_score": round(result.fused_score, 6),
                    "normalized_score": round(result.normalized_score, 4),
                    "channel_scores": result.channel_scores,
                    "channel_ranks": result.channel_ranks,
                }
                for result in hybrid_results[:5]
            ]
            hybrid_meta["hybrid_winner"] = hybrid_results[0].pack_id if hybrid_results else baseline_winner
            hybrid_meta["disagreement"] = hybrid_meta["hybrid_winner"] != baseline_winner
            if request.route_profile in {"hybrid_v4", "hybrid_v5"}:
                retrieval_weight = self.rules.weights.get("hybrid_retrieval", 24)
                candidates = [
                    _ScoredRecord(
                        item.record,
                        item.score.model_copy(
                            update={
                                "retrieval_fit": round(
                                    by_id.get(item.record.manifest.pack_id).normalized_score
                                    * retrieval_weight
                                )
                                if item.record.manifest.pack_id in by_id
                                else 0,
                                "total": item.score.total
                                + (
                                    round(
                                        by_id[item.record.manifest.pack_id].normalized_score
                                        * retrieval_weight
                                    )
                                    if item.record.manifest.pack_id in by_id
                                    else 0
                                ),
                            }
                        ),
                    )
                    for item in candidates
                ]
                candidates.sort(
                    key=lambda item: (
                        -item.score.total,
                        item.record.manifest.token_budget_hint,
                        item.record.manifest.pack_id,
                    )
                )
                hybrid_meta["promoted_winner"] = candidates[0].record.manifest.pack_id
        if request.route_profile == "hybrid_v5":
            baseline_confidence = route_confidence(candidates, normalized, request, self.rules)
            candidate_payloads = [
                {
                    "pack_id": item.record.manifest.pack_id,
                    "score": item.score.total,
                    "family": item.record.manifest.family,
                    "tones": item.record.manifest.tones[:8],
                    "surfaces": item.record.manifest.surfaces[:10],
                    "motif_tags": item.record.manifest.motif_tags[:16],
                    "supports_tasks": item.record.manifest.supports_tasks[:10],
                    "matched_terms": item.score.matched_terms,
                    "pixel_profile": self.hybrid_retriever.pixel_profiles.get(
                        item.record.manifest.pack_id,
                        {},
                    ),
                }
                for item in candidates[:5]
            ]
            local_rerank_meta = rerank_candidates(
                request,
                candidate_payloads,
                mode=request.rerank_mode,
                max_promotion_gap=self.rules.weights.get("local_rerank_max_gap", 18),
            )
            if local_rerank_meta.get("promote") and baseline_confidence["needs_clarification"]:
                local_rerank_meta = {
                    **local_rerank_meta,
                    "promote": False,
                    "promotion_bonus": 0,
                    "reason_code": "baseline_requires_clarification",
                }
            if local_rerank_meta.get("promote"):
                winner = str(local_rerank_meta["winner"])
                bonus = int(local_rerank_meta["promotion_bonus"])
                candidates = [
                    _ScoredRecord(
                        item.record,
                        item.score.model_copy(
                            update={
                                "rerank_fit": bonus,
                                "total": item.score.total + bonus,
                            }
                        ),
                    )
                    if item.record.manifest.pack_id == winner
                    else item
                    for item in candidates
                ]
                candidates.sort(
                    key=lambda item: (
                        -item.score.total,
                        item.record.manifest.token_budget_hint,
                        item.record.manifest.pack_id,
                    )
                )
                local_rerank_meta["promoted_winner"] = candidates[0].record.manifest.pack_id
        return candidates, {
            "initial_anchor_count": initial_count,
            "surface_gate_count": len(surface_candidates),
            "archetype_gate_count": len(archetype_candidates),
            "surface_kind": normalized.surface_kind,
            "task_archetype": normalized.task_archetype,
            "task_archetype_confidence": normalized.task_archetype_confidence,
            "task_archetype_ambiguous": normalized.task_archetype_ambiguous,
            "task_archetype_candidates": [
                candidate.model_dump(mode="json") for candidate in normalized.task_archetype_candidates
            ],
            "hybrid_retrieval": hybrid_meta,
            "local_reranker": local_rerank_meta,
        }

    def _rank_anchors(self, request: DesignContextRequest, normalized) -> list[_ScoredRecord]:
        return self._rank_anchors_with_meta(request, normalized)[0]

    def _effective_donor_first(self, request: DesignContextRequest, normalized) -> bool:
        if request.donor_selection_mode == "site_donor_first_v1":
            return True
        if request.donor_selection_mode != "auto_lane_promotion_v1":
            return False
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        return bool(vertical and vertical.auto_donor_first)

    def _pick_hero_reference_record(self, anchor: _ScoredRecord, normalized) -> PackIndexRecord | None:
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        if vertical is None:
            return None
        for pack_id in vertical.hero_reference_pack_ids:
            if pack_id == anchor.record.manifest.pack_id:
                continue
            record = self.index.by_id.get(pack_id)
            if record is not None and record.manifest.role == "anchor":
                return record
        return None

    def _support_bank_candidates(
        self,
        request: DesignContextRequest,
        normalized,
    ) -> list[PackIndexRecord]:
        banks = self.index.support_banks
        if normalized.surface_kind == "game":
            compatible = [
                bank
                for bank in banks
                if "game_ui" in bank.manifest.supports_tasks
            ]
            if compatible:
                banks = compatible
        elif (
            normalized.specialty_service_class in _DOMAIN_TOKEN_GROUPS
            and normalized.specialty_service_class != "browser_game"
        ):
            compatible = [
                bank
                for bank in banks
                if bank.manifest.family == "website.local_service"
            ]
            if compatible:
                banks = compatible
        donor_first = self._effective_donor_first(request, normalized)
        if donor_first:
            preferred = [b for b in banks if b.manifest.pack_id in self.rules.donor_first_support_bank_ids]
            if preferred:
                banks = preferred
        elif len(banks) > 1:
            banks = [b for b in banks if b.manifest.pack_id not in self.rules.donor_first_support_bank_ids] or banks
        return banks

    def _pick_support_bank(self, request: DesignContextRequest, normalized) -> _ScoredRecord | None:
        banks = self._support_bank_candidates(request, normalized)
        if not banks:
            return None
        scored = [_ScoredRecord(record, self._score_record(request, normalized, record)) for record in banks]
        scored.sort(key=lambda item: (-item.score.total, item.record.manifest.pack_id))
        return scored[0]

    def _support_example_limit(self, request: DesignContextRequest, normalized, support: PackIndexRecord | None, hero: PackIndexRecord | None) -> int:
        if support is None:
            return 0
        if normalized.surface_kind == "game":
            return min(1, len(support.manifest.example_ids))
        if self._effective_donor_first(request, normalized):
            used = 1 + (1 if hero is not None else 0)
            return max(0, min(len(support.manifest.example_ids), request.donor_count - used))
        if request.include_full_library:
            return len(support.manifest.example_ids)
        return max(
            0,
            min(len(support.manifest.example_ids), request.max_examples - 1),
        )

    def _infer_request_ux_roles(self, request: DesignContextRequest, normalized) -> set[str]:
        text = " ".join(
            [
                request.surface,
                request.task,
                request.layout_mode,
                request.stack,
                *request.constraints,
                *request.anti_patterns,
                *request.tone,
                *normalized.motif_tags,
                *normalized.strength_tags,
            ]
        )
        return _infer_ux_roles_from_text(text)

    @staticmethod
    def _anchor_covered_roles(anchor_record: PackIndexRecord) -> set[str]:
        manifest = anchor_record.manifest
        text = " ".join(
            [
                manifest.pack_id,
                manifest.family,
                *manifest.surfaces,
                *manifest.motif_tags,
                *manifest.supports_tasks,
            ]
        ).replace("_", " ").replace("-", " ")
        return _infer_ux_roles_from_text(text)

    def _anchor_is_self_sufficient(
        self,
        request: DesignContextRequest,
        normalized,
        anchor_record: PackIndexRecord,
    ) -> bool:
        requested_roles = set(self._priority_request_roles(request, normalized))
        if not requested_roles:
            return False
        covered_roles = self._anchor_covered_roles(anchor_record)
        manifest = anchor_record.manifest
        if not requested_roles.issubset(covered_roles):
            return False
        if manifest.confidence_score < 5 or not manifest.source_paths:
            return False
        if normalized.surface_kind == "game":
            return manifest.family == "website.game"
        if normalized.surface_kind in {"landing", "docs"}:
            return manifest.family.startswith("website") and manifest.family != "website.game"
        if normalized.surface_kind in {"app", "dashboard"}:
            return manifest.family in _APP_FAMILIES
        if normalized.surface_kind == "instrument":
            return manifest.family in _INSTRUMENT_FAMILIES
        return False

    def _atom_tag_terms(self, request: DesignContextRequest, normalized) -> set[str]:
        """Free-form terms matched against atom tags/category for relevance.

        Includes the request task tokens, declared/normalized tone, and the
        normalized motif/strength tags so a contact/intake request surfaces a form
        atom, a pricing request surfaces pricing, etc. Deterministic (set of tokens).
        """
        terms: set[str] = set()
        terms.update(_tokens_from_text(request.task))
        terms.update(t.lower() for t in request.tone)
        terms.update(t.lower() for t in normalized.tone)
        for tag in [*normalized.motif_tags, *normalized.strength_tags]:
            for piece in tag.lower().replace("-", " ").replace("_", " ").split():
                terms.add(piece)
        terms.update(
            token[:-1]
            for token in list(terms)
            if len(token) > 4 and token.endswith("s")
        )
        return terms

    def _select_shared_atoms(
        self,
        request: DesignContextRequest,
        normalized,
        anchor_record: PackIndexRecord,
        *,
        mode: str,
    ) -> list[AtomSnippet]:
        anchor_roles = self._anchor_covered_roles(anchor_record)
        request_roles = set(self._priority_request_roles(request, normalized)).difference(anchor_roles)
        tone = {*(t.lower() for t in request.tone), *(t.lower() for t in normalized.tone)}
        tag_terms = (
            set()
            if self._anchor_is_self_sufficient(request, normalized, anchor_record)
            else self._atom_tag_terms(request, normalized)
        )
        return select_shared_atoms(
            self.shared_atoms,
            mode=mode,
            surface=request.surface,
            surface_kind=normalized.surface_kind,
            request_roles=request_roles,
            tone=tone,
            tag_terms=tag_terms,
            covered_roles=anchor_roles,
        )

    @staticmethod
    def _starvation_meta(reason: str = "") -> dict[str, Any]:
        return {
            "native_count": 0,
            "mechanical_donor_count": 0,
            "mechanical_donors": [],
            "request_ux_roles": [],
            "anchor_covered_roles": [],
            "uncovered_ux_roles": [],
            "anchor_self_sufficient": False,
            "explicitly_named_examples": [],
            "dropped_for": {
                "blocked_tokens": 0,
                "preferred_required": 0,
                "domain_mismatch": 0,
                "archetype_mismatch": 0,
                "conflict": 0,
                "ux_role_miss": 0,
            },
            "reason": reason,
        }

    def _pick_support_examples(
        self,
        request: DesignContextRequest,
        normalized,
        anchor_record: PackIndexRecord,
        hero_record: PackIndexRecord | None,
        support_record: PackIndexRecord | None,
    ) -> tuple[list[ExampleSelection], dict[str, Any]]:
        starvation_meta = self._starvation_meta("not evaluated")
        request_roles = set(self._priority_request_roles(request, normalized))
        anchor_roles = self._anchor_covered_roles(anchor_record)
        uncovered_roles = sorted(request_roles.difference(anchor_roles))
        anchor_self_sufficient = self._anchor_is_self_sufficient(
            request,
            normalized,
            anchor_record,
        )
        starvation_meta.update(
            {
                "request_ux_roles": sorted(request_roles),
                "anchor_covered_roles": sorted(anchor_roles),
                "uncovered_ux_roles": uncovered_roles,
                "anchor_self_sufficient": anchor_self_sufficient,
            }
        )
        explicitly_named_examples: list[str] = []
        if support_record is not None:
            task_phrase = _ordered_phrase(request.task)
            anchor_tokens = _manifest_tokens(anchor_record.manifest)
            explicitly_named_examples = [
                example_id
                for example_id in support_record.manifest.example_ids
                if f" {_ordered_phrase(example_id)} " in f" {task_phrase} "
                and not _tokens_from_text(
                    example_id.replace("-", " ").replace("_", " ")
                ).issubset(anchor_tokens)
            ]
        starvation_meta["explicitly_named_examples"] = explicitly_named_examples
        if anchor_self_sufficient and not explicitly_named_examples:
            starvation_meta["reason"] = (
                "anchor covers requested ux roles; secondary support donors withheld"
            )
            return [], starvation_meta
        if support_record is None:
            starvation_meta["reason"] = "no support bank selected"
            return [], starvation_meta
        limit = self._support_example_limit(request, normalized, support_record, hero_record)
        if limit <= 0:
            starvation_meta["reason"] = "support example limit is zero"
            return [], starvation_meta

        manifest = support_record.manifest
        blocked_ids = set(anchor_record.manifest.origin_example_ids)
        if hero_record is not None:
            blocked_ids.update(hero_record.manifest.origin_example_ids)
        tokens = request_tokens(request)
        if normalized.surface_kind == "game":
            tokens.update(self._optional_pattern_terms(request, normalized))
        stop_tokens = set(self.rules.generic_example_stop_tokens)
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        prefer_tokens = set(vertical.prefer_example_tokens) if vertical else set()
        blocked_tokens = set(vertical.blocked_example_tokens) if vertical else set()
        request_domain = normalized.specialty_service_class
        if normalized.surface_kind == "game":
            request_domain = "browser_game"
        archetype_hint_order = tuple(
            _ARCHETYPE_PATTERN_EXAMPLE_HINTS.get(
                normalized.task_archetype or "",
                (),
            )
        )
        archetype_hints = set(archetype_hint_order)
        archetype_hint_bonus = {
            example_id: (len(archetype_hint_order) - index) * 2
            for index, example_id in enumerate(archetype_hint_order)
        }
        task_phrase = _ordered_phrase(request.task)
        weights = self.rules.weights

        selections: list[ExampleSelection] = []
        for example_id in manifest.example_ids:
            if example_id in blocked_ids:
                starvation_meta["dropped_for"]["conflict"] += 1
                continue
            example_tokens = _tokens_from_text(example_id.replace("-", " ").replace("_", " "))
            candidate_domains = _infer_pattern_domains(example_tokens)
            if (
                manifest.family == "website.local_service"
                and request_domain in _DOMAIN_TOKEN_GROUPS
                and request_domain not in candidate_domains
            ):
                starvation_meta["dropped_for"]["domain_mismatch"] += 1
                continue
            if (
                normalized.surface_kind == "game"
                and archetype_hints
                and example_id not in archetype_hints
            ):
                starvation_meta["dropped_for"]["archetype_mismatch"] += 1
                continue
            if blocked_tokens and example_tokens.intersection(blocked_tokens) and not example_tokens.intersection(prefer_tokens):
                starvation_meta["dropped_for"]["blocked_tokens"] += 1
                continue
            strengths = set(manifest.example_strengths.get(example_id, []))
            motifs = set(manifest.motif_overlaps.get(example_id, []))
            strength_overlap = sorted(strengths.intersection(normalized.strength_tags))
            motif_overlap = sorted(motifs.intersection(normalized.motif_tags))
            conflicting_strengths = sorted(strengths.intersection(normalized.avoided_strength_tags))
            conflicting_motifs = sorted(motifs.intersection(normalized.avoided_motif_tags))
            request_overlap = sorted(tokens.intersection(example_tokens).difference(stop_tokens))
            preferred_overlap = sorted(prefer_tokens.intersection(example_tokens))
            if normalized.specialty_service_class == "combat_sports" and not preferred_overlap:
                starvation_meta["dropped_for"]["preferred_required"] += 1
                continue

            score = 0
            score += len(strength_overlap) * weights.get("strength", 3)
            score += len(motif_overlap) * weights.get("motif", 4)
            score += min(12, len(request_overlap) * weights.get("request_token_example", 3))
            score += len(preferred_overlap) * weights.get("preferred_example_token", 12)
            score += archetype_hint_bonus.get(example_id, 0)
            example_phrase = _ordered_phrase(example_id)
            if example_phrase and f" {example_phrase} " in f" {task_phrase} ":
                score += 24
            score -= len(conflicting_strengths) * weights.get("conflict_strength", 4)
            score -= len(conflicting_motifs) * weights.get("conflict_motif", 3)
            if request.layout_mode in {"homepage", "landing"} and "section_sequencing" in strengths:
                score += 4
            if normalized.prefers_light_mode and ("light_clarity" in strengths or "light_precision" in motifs):
                score += 4
            if normalized.prefers_warm_mode and {"premium_spacing", "visual_restraint"}.intersection(strengths):
                score += 4
            if normalized.avoids_dark_mode and {"dark_contrast", "industrial_tone"}.intersection(strengths):
                score -= 8
            if score <= 0 and not request.include_full_library:
                starvation_meta["dropped_for"]["conflict"] += 1
                continue
            selections.append(
                ExampleSelection(
                    example_id=example_id,
                    score=int(score),
                    strength_overlap=strength_overlap,
                    motif_overlap=motif_overlap,
                    conflicting_strength_tags=conflicting_strengths,
                    conflicting_motif_tags=conflicting_motifs,
                    matched_tokens=sorted(set(request_overlap + preferred_overlap)),
                )
            )
        selections.sort(
            key=lambda item: (
                len(item.conflicting_strength_tags) + len(item.conflicting_motif_tags),
                -item.score,
                item.example_id,
            )
        )
        native = selections[:limit]
        if native:
            starvation_meta["native_count"] = len(native)
            starvation_meta["reason"] = "native support selected"
            return native, starvation_meta

        fallback_roles = set(vertical.ux_role_fallback) if vertical else set()
        if not fallback_roles:
            starvation_meta["reason"] = "no ux_role_fallback configured"
            return [], starvation_meta
        fallback_request_roles = sorted(
            self._infer_request_ux_roles(request, normalized).intersection(fallback_roles)
        )
        starvation_meta["request_ux_roles"] = fallback_request_roles
        if not fallback_request_roles:
            starvation_meta["reason"] = "no inferable ux_roles"
            return [], starvation_meta

        mechanical: list[ExampleSelection] = []
        blocked_mechanical: list[ExampleSelection] = []
        for example_id in manifest.example_ids:
            if example_id in blocked_ids:
                continue
            example_tokens = _tokens_from_text(example_id.replace("-", " ").replace("_", " "))
            blocked_by_vertical = bool(blocked_tokens and example_tokens.intersection(blocked_tokens) and not example_tokens.intersection(prefer_tokens))
            ux_roles = set(manifest.example_ux_roles.get(example_id, [])).intersection(fallback_roles)
            overlap = sorted(ux_roles.intersection(fallback_request_roles))
            if not overlap:
                starvation_meta["dropped_for"]["ux_role_miss"] += 1
                continue
            selection = ExampleSelection(
                example_id=example_id,
                score=int(len(overlap) * weights.get("ux_role_overlap", 5)),
                strength_overlap=[],
                motif_overlap=[],
                matched_tokens=overlap,
                ux_role_match=overlap,
            )
            if blocked_by_vertical:
                blocked_mechanical.append(selection)
            else:
                mechanical.append(selection)
        mechanical.sort(key=lambda item: (-item.score, item.example_id))
        blocked_mechanical.sort(key=lambda item: (-item.score, item.example_id))
        if not mechanical:
            mechanical = blocked_mechanical
        mechanical_limit = min(limit, max(1, request.donor_count - 1))
        mechanical = mechanical[:mechanical_limit]
        starvation_meta["mechanical_donor_count"] = len(mechanical)
        starvation_meta["mechanical_donors"] = [item.example_id for item in mechanical]
        starvation_meta["reason"] = "native donor starvation; selected mechanical donors by ux_role" if mechanical else "no mechanical donors matched request ux_roles"
        return mechanical, starvation_meta

    def _optional_pattern_limit(self, request: DesignContextRequest, *, mode: str) -> int:
        if not request.include_optional_patterns or request.optional_pattern_count <= 0:
            return 0
        return request.optional_pattern_count

    def _optional_pattern_terms(self, request: DesignContextRequest, normalized) -> set[str]:
        terms = request_tokens_for_compatibility(request)
        archetype = self.rules.task_archetypes.get(normalized.task_archetype or "")
        if archetype is not None:
            terms.update(_tokens_from_text(" ".join([*archetype.keywords, *archetype.aliases])))
        semantic_text = " ".join(
            [
                request.task,
                normalized.task_archetype or "",
                normalized.specialty_service_class or "",
            ]
        ).lower()
        for trigger, expansions in _PATTERN_TERM_EXPANSIONS.items():
            if trigger in semantic_text:
                terms.update(expansions)
        return terms.difference(_GENERIC_ROUTE_TOKENS)

    def _explicit_request_ux_roles(self, request: DesignContextRequest) -> set[str]:
        return _infer_ux_roles_from_text(
            " ".join(
                [
                    request.surface,
                    request.task,
                    request.layout_mode,
                    *request.constraints,
                    *request.anti_patterns,
                    *request.tone,
                ]
            )
        )

    def _priority_request_roles(self, request: DesignContextRequest, normalized) -> list[str]:
        explicit_roles = self._explicit_request_ux_roles(request)
        inferred_roles = self._infer_request_ux_roles(request, normalized)
        if normalized.surface_kind == "game":
            explicit_roles.intersection_update(_GAME_UX_ROLES)
            inferred_roles.intersection_update(_GAME_UX_ROLES)
        requested_roles = explicit_roles.union(inferred_roles)
        preset_key = normalized.task_archetype or normalized.specialty_service_class or ""
        preset = _PRIORITY_ROLE_PRESETS.get(preset_key, ())
        if not preset and normalized.specialty_service_class == "browser_game":
            preset = _PRIORITY_ROLE_PRESETS["browser_game"]
        ordered: list[str] = []
        for role in [
            *(role for role in preset if role in requested_roles),
            *sorted(explicit_roles),
            *sorted(inferred_roles),
        ]:
            if role in _GENERIC_PATTERN_ROLES and role not in explicit_roles:
                continue
            if role not in ordered:
                ordered.append(role)
        return ordered

    @staticmethod
    def _candidate_domain_fit(normalized, manifest: PackManifest, example_tokens: set[str]) -> str | None:
        request_domain = normalized.specialty_service_class
        if normalized.task_archetype in {"arcade_game", "tactics_game", "game"}:
            request_domain = "browser_game"
        candidate_domains = _infer_pattern_domains(example_tokens)
        if candidate_domains:
            if request_domain in candidate_domains:
                return "native"
            return None
        if manifest.family == "website.local_service" and request_domain:
            return None
        return "neutral"

    @staticmethod
    def _pattern_states(roles: set[str]) -> list[str]:
        states: list[str] = []
        if "form_intake" in roles or "consultation_flow" in roles:
            states.extend(["idle", "focus", "invalid", "submitting", "success", "error"])
        if "schedule_grid" in roles:
            states.extend(["available", "selected", "unavailable"])
        if "modal_flow" in roles or "overlay_state" in roles:
            states.extend(["closed", "open"])
        if "overlay_state" in roles:
            states.extend(["paused", "victory", "defeat", "reward"])
        if "navigation_shell" in roles or "header_sticky" in roles:
            states.extend(["collapsed", "expanded", "focus-visible"])
        if "filter_toolbar" in roles:
            states.extend(["idle", "filtered", "empty"])
        return list(dict.fromkeys(states))

    @staticmethod
    def _pattern_responsive_behavior(roles: set[str]) -> list[str]:
        rules = ["Preserve the anchor container and spacing tokens; this card does not define page-wide geometry."]
        if roles.intersection({"data_table", "schedule_grid"}):
            rules.append("At narrow widths, stack or horizontally scroll the dense grid with a visible affordance; never squeeze it to illegibility.")
        if roles.intersection({"hud_cluster", "responsive_control_dock", "gameplay_stage"}):
            rules.append("At 390px and 360px, keep controls at least 44x44px and prevent the HUD, overlays, and touch zones from colliding.")
        if roles.intersection({"navigation_shell", "header_sticky"}):
            rules.append("Collapse navigation without covering the first content block; preserve visible focus and anchor offsets.")
        if roles.intersection({"form_intake", "consultation_flow"}):
            rules.append("Stack fields and actions in source order on mobile without losing entered values or validation context.")
        return rules

    @staticmethod
    def _pattern_invariants(roles: set[str]) -> list[str]:
        invariants = ["One pattern card solves one named job and never replaces the primary anchor."]
        if "proof_rail" in roles or "trust_rail" in roles:
            invariants.append("Every proof value must come from the brief; omit unsupported claims instead of fabricating them.")
        if "form_intake" in roles:
            invariants.append("Every field has a programmatic label and explicit error, loading, and success handling.")
        if "schedule_grid" in roles:
            invariants.append("Time, program, and availability remain distinguishable without relying on color alone.")
        if "overlay_state" in roles or "modal_flow" in roles:
            invariants.append("Overlay state is keyboard reachable, dismissible where appropriate, and restores focus.")
        if "gameplay_stage" in roles:
            invariants.append("The playable surface remains the first-viewport authority; supporting UI cannot turn it into a landing page.")
        return invariants

    @staticmethod
    def _pattern_integration_hint(roles: set[str]) -> str:
        if roles.intersection({"hud_cluster", "overlay_state", "responsive_control_dock", "gameplay_stage"}):
            return "Integrate inside the anchor's authoritative game stage; do not create a second page shell."
        if roles.intersection({"navigation_shell", "header_sticky"}):
            return "Adapt inside the anchor's existing header/navigation slot."
        if roles.intersection({"form_intake", "consultation_flow"}):
            return "Place at the anchor's conversion point after enough context and proof have been established."
        if roles.intersection({"proof_rail", "trust_rail", "stats_strip"}):
            return "Place where the anchor transitions from promise to evidence."
        if roles.intersection({"schedule_grid", "service_lane_set", "process_steps"}):
            return "Use as one interior section while preserving the anchor's surrounding rhythm and section order."
        return "Use only inside an existing anchor slot that already serves the same job."

    def _pattern_dependencies(self, roles: set[str], shared_atoms: list[AtomSnippet]) -> list[str]:
        dependencies: list[str] = []
        for atom in shared_atoms:
            atom_roles = {role.lower() for role in atom.ux_roles}
            if atom.atom_id == "foundation_design_tokens_v1" or roles.intersection(atom_roles):
                dependencies.append(atom.atom_id)
            if len(dependencies) >= 4:
                break
        return dependencies

    def _pattern_contract(
        self,
        *,
        roles: list[str],
        priority_roles: list[str],
        source_kind: str,
        domain_fit: str,
        shared_atoms: list[AtomSnippet],
    ) -> dict[str, Any]:
        role_set = set(roles)
        primary_role = next((role for role in priority_roles if role in role_set), roles[0] if roles else "")
        job = _PATTERN_JOB_BY_ROLE.get(primary_role, "Provide one bounded interaction or section mechanic.")
        return {
            "job_statement": job,
            "when_to_use": f"Use when the brief needs `{primary_role or 'this exact mechanic'}` and the primary anchor does not already solve it clearly.",
            "when_not_to_use": "Do not use when it duplicates an anchor section, adds a second identity, or introduces copy/claims not supplied by the brief.",
            "states": self._pattern_states(role_set),
            "responsive_behavior": self._pattern_responsive_behavior(role_set),
            "invariants": self._pattern_invariants(role_set),
            "dependencies": self._pattern_dependencies(role_set, shared_atoms),
            "integration_hint": self._pattern_integration_hint(role_set),
            "identity_risk": "high" if source_kind == "anchor_excerpt" else "low" if domain_fit == "native" else "medium",
        }

    @staticmethod
    def _optional_pattern_surface_fit(request: DesignContextRequest, normalized, manifest: PackManifest) -> int:
        family = manifest.family
        kind = normalized.surface_kind
        if kind == "game":
            if family == "app.tool":
                return 24
            if family == "website.pattern_library":
                return 10
            if family == "website.local_service":
                return -48
        if kind in {"app", "instrument"}:
            if family == "app.tool":
                return 20
            if family == "website.pattern_library":
                return 10
            if family == "website.local_service":
                return -36
        if kind in {"landing", "docs"}:
            if family == "website.local_service":
                return 18 if normalized.specialty_service_class not in {None, "browser_game"} else 6
            if family == "website.pattern_library":
                return 10
            if family == "app.tool":
                return -8
        return 0

    def _rank_optional_example_candidates(
        self,
        request: DesignContextRequest,
        normalized,
        *,
        anchor_record: PackIndexRecord,
        hero_record: PackIndexRecord | None,
        support_record: PackIndexRecord | None,
        selected_examples: list[ExampleSelection],
    ) -> list[_OptionalExampleCandidate]:
        terms = self._optional_pattern_terms(request, normalized)
        priority_roles = self._priority_request_roles(request, normalized)
        request_roles = set(priority_roles)
        explicit_roles = self._explicit_request_ux_roles(request)
        selected_keys = {
            (support_record.manifest.pack_id, selection.example_id)
            for selection in selected_examples
            if support_record is not None
        }
        blocked_ids = set(anchor_record.manifest.origin_example_ids)
        if hero_record is not None:
            blocked_ids.update(hero_record.manifest.origin_example_ids)
        vertical = self.rules.verticals.get(normalized.specialty_service_class or "")
        preferred_tokens = set(vertical.prefer_example_tokens) if vertical else set()
        blocked_tokens = set(vertical.blocked_example_tokens) if vertical else set()
        hinted_examples = set(_ARCHETYPE_PATTERN_EXAMPLE_HINTS.get(normalized.task_archetype or "", ()))

        ranked: list[_OptionalExampleCandidate] = []
        for record in self.index.support_banks:
            manifest = record.manifest
            bank_score = self._score_record(request, normalized, record)
            bank_component = max(-12, min(16, bank_score.total // 10))
            surface_fit = self._optional_pattern_surface_fit(request, normalized, manifest)
            for example_id in manifest.example_ids:
                if (manifest.pack_id, example_id) in selected_keys or example_id in blocked_ids:
                    continue
                strengths = set(manifest.example_strengths.get(example_id, []))
                motifs = set(manifest.motif_overlaps.get(example_id, []))
                role_evidence_text = " ".join(
                    [
                        example_id,
                        *strengths,
                        *motifs,
                    ]
                ).replace("_", " ").replace("-", " ")
                metadata_text = " ".join(
                    [
                        role_evidence_text,
                        *manifest.example_ux_roles.get(example_id, []),
                    ]
                )
                example_tokens = _tokens_from_text(example_id.replace("_", " ").replace("-", " "))
                domain_fit = self._candidate_domain_fit(normalized, manifest, example_tokens)
                if domain_fit is None:
                    continue
                metadata_tokens = _tokens_from_text(metadata_text)
                inferred_roles = _infer_ux_roles_from_text(role_evidence_text)
                declared_roles = set(manifest.example_ux_roles.get(example_id, []))
                candidate_roles = set(inferred_roles)
                if manifest.family != "app.tool":
                    candidate_roles.update(declared_roles)
                role_overlap = sorted(request_roles.intersection(candidate_roles))
                direct_overlap = sorted(terms.intersection(example_tokens))
                metadata_overlap = sorted(terms.intersection(metadata_tokens))
                strength_overlap = sorted(strengths.intersection(normalized.strength_tags))
                motif_overlap = sorted(motifs.intersection(normalized.motif_tags))
                preferred_overlap = sorted(terms.intersection(preferred_tokens).intersection(example_tokens))
                hinted = example_id in hinted_examples
                conflicting_strengths = strengths.intersection(normalized.avoided_strength_tags)
                conflicting_motifs = motifs.intersection(normalized.avoided_motif_tags)
                blocked_overlap = blocked_tokens.intersection(example_tokens)
                if (
                    normalized.surface_kind == "game"
                    and hinted_examples
                    and example_id not in hinted_examples
                ):
                    continue

                fuzzy_matches: list[str] = []
                for term in sorted(terms):
                    if len(term) < 5 or term in metadata_tokens:
                        continue
                    match = max(
                        (
                            token
                            for token in metadata_tokens
                            if len(token) >= 5 and SequenceMatcher(None, term, token).ratio() >= 0.86
                        ),
                        key=lambda token: SequenceMatcher(None, term, token).ratio(),
                        default="",
                    )
                    if match:
                        fuzzy_matches.append(f"{term}~{match}")

                specific_role_overlap = set(role_overlap).difference(_GENERIC_PATTERN_ROLES)
                explicit_generic_overlap = set(role_overlap).intersection(_GENERIC_PATTERN_ROLES).intersection(explicit_roles)
                explicit_role_overlap = set(role_overlap).intersection(explicit_roles)
                explicit_specific_role_overlap = explicit_role_overlap.difference(
                    _GENERIC_PATTERN_ROLES
                )
                semantic_signal = bool(
                    specific_role_overlap
                    or explicit_generic_overlap
                    or direct_overlap
                    or strength_overlap
                    or motif_overlap
                    or preferred_overlap
                    or hinted
                )
                if not semantic_signal:
                    continue
                if domain_fit == "neutral" and not (
                    explicit_specific_role_overlap
                    or direct_overlap
                    or preferred_overlap
                    or hinted
                ):
                    continue
                if (
                    normalized.surface_kind in {"landing", "docs"}
                    and manifest.family == "app.tool"
                    and domain_fit == "neutral"
                    and not (direct_overlap or preferred_overlap or hinted)
                ):
                    continue
                if (
                    set(candidate_roles).issubset(_GENERIC_PATTERN_ROLES)
                    and not explicit_generic_overlap
                    and not direct_overlap
                    and not preferred_overlap
                    and not hinted
                ):
                    continue
                if normalized.surface_kind == "game" and domain_fit != "native":
                    continue
                if normalized.surface_kind == "game" and manifest.family == "app.tool":
                    native_game_signal = bool(
                        direct_overlap
                        or preferred_overlap
                        or hinted
                        or "interactive_stage" in motif_overlap
                        or "single_screen_stage" in strength_overlap
                    )
                    if not native_game_signal:
                        continue

                domain_axis = 32 if domain_fit == "native" else 14
                mechanic_axis = min(
                    100,
                    (len(role_overlap) * 18)
                    + (len(direct_overlap) * 20)
                    + (len(preferred_overlap) * 14)
                    + (len(motif_overlap) * 8)
                    + (18 if hinted else 0),
                )
                quality_score = min(
                    100,
                    (manifest.confidence_score * 14)
                    + min(16, len(strengths) * 2)
                    + min(12, len(motifs) * 2),
                )
                conflict_axis = -(
                    (len(conflicting_strengths) * 8)
                    + (len(conflicting_motifs) * 6)
                )
                lexical_axis = min(
                    30,
                    (len(direct_overlap) * 12)
                    + (len(metadata_overlap) * 2)
                    + (len(fuzzy_matches) * 2),
                )
                score_axes = {
                    "domain": domain_axis,
                    "mechanic": mechanic_axis,
                    "quality": quality_score // 4,
                    "surface": surface_fit,
                    "bank": bank_component,
                    "lexical": lexical_axis,
                    "conflict": conflict_axis,
                }
                score = sum(score_axes.values())
                if blocked_overlap and not direct_overlap and not preferred_overlap:
                    continue
                if support_record is not None and manifest.pack_id == support_record.manifest.pack_id:
                    score += 4
                if score <= 0:
                    continue

                ranked.append(
                    _OptionalExampleCandidate(
                        record=record,
                        example_id=example_id,
                        score=int(score),
                        ux_roles=tuple(sorted(candidate_roles)),
                        matched_terms=tuple(sorted(set(direct_overlap + metadata_overlap + preferred_overlap + fuzzy_matches))),
                        strength_tags=tuple(strength_overlap),
                        motif_tags=tuple(motif_overlap),
                        score_axes=tuple(sorted(score_axes.items())),
                        domain_fit=domain_fit,
                        mechanic_fit=mechanic_axis,
                        quality_score=quality_score,
                        identity_risk="low" if domain_fit == "native" else "medium",
                    )
                )

        ranked.sort(key=lambda item: (-item.score, item.record.manifest.pack_id, item.example_id))
        deduped: dict[str, _OptionalExampleCandidate] = {}
        for candidate in ranked:
            deduped.setdefault(candidate.example_id, candidate)
        return sorted(
            deduped.values(),
            key=lambda item: (-item.score, item.record.manifest.pack_id, item.example_id),
        )

    def _best_optional_excerpt(
        self,
        example,
        *,
        terms: set[str],
        request_roles: set[str],
    ) -> tuple[CodeFile | None, set[str], list[str], int]:
        excerpts = list(example.section_job_excerpts)
        if not excerpts and example.html_excerpt:
            excerpts = [
                CodeFile(
                    label=f"{example.example_id}/primary-fragment.html",
                    language="html",
                    content=example.html_excerpt,
                )
            ]
        scored: list[tuple[int, str, CodeFile, set[str], list[str]]] = []
        for excerpt in excerpts:
            label_tokens = _tokens_from_text(excerpt.label.replace("_", " ").replace("-", " "))
            content_tokens = _tokens_from_text(excerpt.content)
            excerpt_roles = _infer_ux_roles_from_text(
                f"{excerpt.label} {excerpt.content[:1800]}"
            )
            role_overlap = request_roles.intersection(excerpt_roles)
            label_overlap = sorted(terms.intersection(label_tokens))
            content_overlap = sorted(terms.intersection(content_tokens))
            if not role_overlap and not label_overlap and not content_overlap:
                continue
            score = len(role_overlap) * 16 + len(label_overlap) * 10 + min(10, len(content_overlap))
            scored.append(
                (
                    score,
                    excerpt.label,
                    excerpt,
                    excerpt_roles,
                    sorted(set(label_overlap + content_overlap)),
                )
            )
        if not scored:
            return None, set(), [], 0
        scored.sort(key=lambda item: (-item[0], item[1]))
        score, _, excerpt, roles, matches = scored[0]
        return excerpt, roles, matches, score

    @staticmethod
    def _diversify_optional_patterns(
        patterns: list[OptionalPattern],
        *,
        limit: int,
        priority_roles: list[str],
    ) -> list[OptionalPattern]:
        if limit <= 0:
            return []
        unique: list[OptionalPattern] = []
        fingerprints: set[str] = set()
        for pattern in sorted(patterns, key=lambda item: (-item.score, item.pattern_id)):
            fingerprint_source = pattern.excerpt.content if pattern.excerpt is not None else pattern.pattern_id
            fingerprint = hashlib.sha256(" ".join(fingerprint_source.split()).encode()).hexdigest()[:16]
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            unique.append(pattern)

        selected: list[OptionalPattern] = []
        pack_counts: dict[str, int] = {}
        covered_roles: set[str] = set()
        priority_order = {role: len(priority_roles) - index for index, role in enumerate(priority_roles)}
        max_per_pack = max(2, (limit + 1) // 2)
        support_remaining = [
            pattern for pattern in unique if pattern.source_kind == "support_example"
        ]
        top_support_score = max((pattern.score for pattern in support_remaining), default=0)
        while support_remaining and len(selected) < limit:
            eligible = [
                pattern
                for pattern in support_remaining
                if pack_counts.get(pattern.pack_id, 0) < max_per_pack
            ]
            if not eligible:
                break
            selected_pack_ids = {pattern.pack_id for pattern in selected}
            chosen = max(
                eligible,
                key=lambda pattern: (
                    pattern.score
                    + sum(
                        priority_order.get(role, 0) * 12
                        for role in set(pattern.priority_roles).difference(covered_roles)
                    )
                    + (1 if pattern.pack_id not in selected_pack_ids else 0),
                    pattern.mechanic_fit,
                    pattern.score,
                    pattern.pattern_id,
                ),
            )
            new_priority_roles = set(chosen.priority_roles).difference(covered_roles)
            if selected and not new_priority_roles:
                score_ratio = chosen.score / max(1, top_support_score)
                previous_score = selected[-1].score
                score_drop = (previous_score - chosen.score) / max(1, previous_score)
                if score_ratio < 0.82 or score_drop > 0.18 or chosen.mechanic_fit < 65:
                    break
            selected.append(chosen)
            support_remaining.remove(chosen)
            pack_counts[chosen.pack_id] = pack_counts.get(chosen.pack_id, 0) + 1
            covered_roles.update(chosen.priority_roles)
        if len(selected) < limit:
            auxiliary = [
                pattern
                for pattern in unique
                if pattern.source_kind == "anchor_excerpt"
                and pack_counts.get(pattern.pack_id, 0) < max_per_pack
                and bool(set(pattern.priority_roles).difference(covered_roles))
            ]
            if auxiliary:
                chosen = max(
                    auxiliary,
                    key=lambda pattern: (
                        sum(
                            priority_order.get(role, 0) * 12
                            for role in set(pattern.priority_roles).difference(covered_roles)
                        ),
                        pattern.mechanic_fit,
                        pattern.score,
                        pattern.pattern_id,
                    ),
                )
                selected.append(chosen)
        return selected

    def _pick_optional_patterns(
        self,
        request: DesignContextRequest,
        normalized,
        *,
        ranked_anchors: list[_ScoredRecord],
        anchor_record: PackIndexRecord,
        hero_record: PackIndexRecord | None,
        support_record: PackIndexRecord | None,
        selected_examples: list[ExampleSelection],
        mode: str,
        max_code_chars: int | None,
        max_atoms: int | None,
        shared_atoms: list[AtomSnippet],
    ) -> tuple[
        list[OptionalPattern],
        list[LoadedPack],
        list[PatternCatalogEntry],
        list[OptionalPattern],
        dict[str, Any],
    ]:
        limit = self._optional_pattern_limit(request, mode=mode)
        meta: dict[str, Any] = {
            "enabled": request.include_optional_patterns,
            "requested_count": request.optional_pattern_count,
            "mode_cap": None,
            "capacity_policy": "unbounded",
            "selected_count": 0,
            "eligible_count": 0,
            "qualified_count": 0,
            "catalog_count": 0,
            "source_pack_count": 0,
            "source_packs": [],
            "priority_roles": [],
            "selection_strategy": "hard_domain_gate_then_priority_role_fill_with_elbow_stop",
            "auxiliary_anchor_cap": 1,
            "hygiene_rejections": 0,
            "max_per_pack": 0,
        }
        if limit <= 0:
            return [], [], [], [], meta

        terms = self._optional_pattern_terms(request, normalized)
        requested_roles = self._priority_request_roles(request, normalized)
        anchor_roles = self._anchor_covered_roles(anchor_record)
        priority_roles = [role for role in requested_roles if role not in anchor_roles]
        anchor_self_sufficient = self._anchor_is_self_sufficient(
            request,
            normalized,
            anchor_record,
        )
        meta.update(
            {
                "requested_roles": requested_roles,
                "anchor_covered_roles": sorted(anchor_roles),
                "uncovered_roles": priority_roles,
                "anchor_self_sufficient": anchor_self_sufficient,
            }
        )
        if anchor_self_sufficient or not priority_roles:
            meta["selection_strategy"] = "anchor_gap_analysis_withheld_redundant_patterns"
            return [], [], [], [], meta
        request_roles = set(priority_roles)
        meta["priority_roles"] = priority_roles
        candidates = self._rank_optional_example_candidates(
            request,
            normalized,
            anchor_record=anchor_record,
            hero_record=hero_record,
            support_record=support_record,
            selected_examples=selected_examples,
        )
        per_pack_limit = max(4, limit)
        shortlisted: list[_OptionalExampleCandidate] = []
        shortlist_pack_counts: dict[str, int] = {}
        for candidate in candidates:
            pack_id = candidate.record.manifest.pack_id
            if shortlist_pack_counts.get(pack_id, 0) >= per_pack_limit:
                continue
            shortlisted.append(candidate)
            shortlist_pack_counts[pack_id] = shortlist_pack_counts.get(pack_id, 0) + 1

        grouped: dict[str, list[_OptionalExampleCandidate]] = {}
        for candidate in shortlisted:
            grouped.setdefault(candidate.record.manifest.pack_id, []).append(candidate)

        patterns: list[OptionalPattern] = []
        for pack_id, pack_candidates in sorted(grouped.items()):
            pack = self.store.get_pack(
                pack_id,
                selected_examples=[candidate.example_id for candidate in pack_candidates],
                include_full=False,
                max_code_chars=max_code_chars,
                max_atoms=max_atoms,
            )
            for candidate in pack_candidates:
                example = pack.example_summaries.get(candidate.example_id)
                if example is None:
                    continue
                excerpt, excerpt_roles, excerpt_matches, excerpt_score = self._best_optional_excerpt(
                    example,
                    terms=terms,
                    request_roles=request_roles,
                )
                if excerpt is None:
                    continue
                roles = sorted(
                    set(excerpt_roles).union(
                        set(candidate.ux_roles).intersection(request_roles)
                    )
                )
                style_excerpt = None
                if example.css_excerpt:
                    style_excerpt = CodeFile(
                        label=f"{candidate.example_id}/pattern.css",
                        language="css",
                        content=example.css_excerpt,
                    )
                hygiene_text = excerpt.content
                if style_excerpt is not None:
                    hygiene_text += "\n" + style_excerpt.content
                hygiene_hits = scan_source_hygiene(hygiene_text)
                if hygiene_hits:
                    meta["hygiene_rejections"] += 1
                    continue
                pattern_id = (
                    f"{pack_id}::{candidate.example_id}::"
                    f"{Path(excerpt.label).stem}"
                )
                card_priority_roles = [role for role in priority_roles if role in roles]
                contract = self._pattern_contract(
                    roles=roles,
                    priority_roles=priority_roles,
                    source_kind="support_example",
                    domain_fit=candidate.domain_fit,
                    shared_atoms=shared_atoms,
                )
                score_axes = dict(candidate.score_axes)
                score_axes["excerpt"] = excerpt_score
                patterns.append(
                    OptionalPattern(
                        pattern_id=pattern_id,
                        pack_id=pack_id,
                        example_id=candidate.example_id,
                        source_kind="support_example",
                        score=candidate.score + excerpt_score,
                        score_axes=score_axes,
                        domain_fit=candidate.domain_fit,  # type: ignore[arg-type]
                        mechanic_fit=candidate.mechanic_fit,
                        quality_score=candidate.quality_score,
                        identity_risk=candidate.identity_risk,  # type: ignore[arg-type]
                        ux_roles=roles,
                        priority_roles=card_priority_roles,
                        matched_terms=sorted(set(candidate.matched_terms).union(excerpt_matches)),
                        strength_tags=list(candidate.strength_tags),
                        motif_tags=list(candidate.motif_tags),
                        job_statement=contract["job_statement"],
                        when_to_use=contract["when_to_use"],
                        when_not_to_use=contract["when_not_to_use"],
                        states=contract["states"],
                        responsive_behavior=contract["responsive_behavior"],
                        invariants=contract["invariants"],
                        dependencies=contract["dependencies"],
                        integration_hint=contract["integration_hint"],
                        excerpt=excerpt,
                        style_excerpt=style_excerpt,
                        hygiene_clean=True,
                    )
                )

        auxiliary_packs: list[LoadedPack] = []
        for item in ranked_anchors[1:4]:
            if item.score.total <= 0 or item.record.manifest.pack_id == anchor_record.manifest.pack_id:
                continue
            if hero_record is not None and item.record.manifest.pack_id == hero_record.manifest.pack_id:
                continue
            if item.record.manifest.family != anchor_record.manifest.family:
                continue
            if normalized.task_archetype in {"arcade_game", "tactics_game"}:
                archetype = self.rules.task_archetypes.get(normalized.task_archetype)
                if archetype is None or item.record.manifest.pack_id not in archetype.preferred_pack_ids:
                    continue
            aux_domain_fit = self._candidate_domain_fit(
                normalized,
                item.record.manifest,
                _tokens_from_text(item.record.manifest.pack_id.replace("_", " ").replace("-", " ")),
            )
            if aux_domain_fit is None:
                continue
            pack = self.store.get_pack(
                item.record.manifest.pack_id,
                include_full=False,
                max_code_chars=max_code_chars,
                max_atoms=max_atoms,
            )
            source_text = " ".join(
                [
                    item.record.manifest.pack_id,
                    item.record.manifest.family,
                    *item.record.manifest.motif_tags,
                    *item.record.manifest.supports_tasks,
                ]
            )
            roles = sorted(_infer_ux_roles_from_text(source_text))
            card_priority_roles = [role for role in priority_roles if role in roles]
            if not card_priority_roles:
                continue
            matches = sorted(terms.intersection(_tokens_from_text(source_text)))
            mechanic_fit = min(100, len(card_priority_roles) * 22 + min(20, len(matches) * 2))
            quality_score = min(100, item.record.manifest.confidence_score * 18)
            contract = self._pattern_contract(
                roles=roles,
                priority_roles=priority_roles,
                source_kind="anchor_excerpt",
                domain_fit=aux_domain_fit,
                shared_atoms=shared_atoms,
            )
            patterns.append(
                OptionalPattern(
                    pattern_id=f"{item.record.manifest.pack_id}::anchor-treatment-summary",
                    pack_id=item.record.manifest.pack_id,
                    source_kind="anchor_excerpt",
                    score=item.score.total + mechanic_fit,
                    score_axes={
                        "anchor_route": item.score.total,
                        "mechanic": mechanic_fit,
                        "identity_risk": -24,
                    },
                    domain_fit=aux_domain_fit,  # type: ignore[arg-type]
                    mechanic_fit=mechanic_fit,
                    quality_score=quality_score,
                    identity_risk="high",
                    ux_roles=roles,
                    priority_roles=card_priority_roles,
                    matched_terms=matches,
                    strength_tags=[],
                    motif_tags=list(item.record.manifest.motif_tags[:6]),
                    job_statement=contract["job_statement"],
                    when_to_use=contract["when_to_use"],
                    when_not_to_use=contract["when_not_to_use"],
                    states=contract["states"],
                    responsive_behavior=contract["responsive_behavior"],
                    invariants=contract["invariants"],
                    dependencies=contract["dependencies"],
                    integration_hint=contract["integration_hint"],
                    excerpt=None,
                    style_excerpt=None,
                    hygiene_clean=True,
                )
            )
            auxiliary_packs.append(pack)

        meta["eligible_count"] = len(patterns)
        qualified = sorted(patterns, key=lambda pattern: (-pattern.score, pattern.pattern_id))
        meta["qualified_count"] = len(qualified)
        max_per_pack = max(2, (limit + 1) // 2)
        meta["max_per_pack"] = max_per_pack
        selected = self._diversify_optional_patterns(
            qualified,
            limit=limit,
            priority_roles=priority_roles,
        )
        selected_pack_ids = {pattern.pack_id for pattern in selected if pattern.source_kind == "anchor_excerpt"}
        auxiliary_packs = [
            pack for pack in auxiliary_packs if pack.manifest.pack_id in selected_pack_ids
        ]
        source_packs = sorted({pattern.pack_id for pattern in selected})
        catalog = [
            PatternCatalogEntry(
                pattern_id=pattern.pattern_id,
                pack_id=pattern.pack_id,
                example_id=pattern.example_id,
                source_kind=pattern.source_kind,
                score=pattern.score,
                domain_fit=pattern.domain_fit,
                mechanic_fit=pattern.mechanic_fit,
                quality_score=pattern.quality_score,
                identity_risk=pattern.identity_risk,
                ux_roles=pattern.ux_roles,
                priority_roles=pattern.priority_roles,
                job_statement=pattern.job_statement,
            )
            for pattern in qualified
        ]
        meta.update(
            {
                "selected_count": len(selected),
                "source_pack_count": len(source_packs),
                "source_packs": source_packs,
                "pattern_ids": [pattern.pattern_id for pattern in selected],
                "catalog_count": len(catalog),
            }
        )
        return selected, auxiliary_packs, catalog, qualified, meta

    def route(self, request: DesignContextRequest) -> RouteResolution:
        normalized = normalize_request(request, self.rules)
        ranked_anchors, candidate_gate = self._rank_anchors_with_meta(request, normalized)
        anchor = ranked_anchors[0]
        # Multi-pattern routing: keep the strongest runner-up anchors so the packet
        # can surface alternative pattern sources, not just the single winner.
        anchor_alternatives = [
            {
                "pack_id": item.record.manifest.pack_id,
                "score": item.score.total,
                "family": item.record.manifest.family,
                "motif_tags": list(item.record.manifest.motif_tags[:6]),
                "tones": list(item.record.manifest.tones[:4]),
                "supports_tasks": list(item.record.manifest.supports_tasks[:3]),
            }
            for item in ranked_anchors[1:4]
            if item.score.total > 0
        ]
        if normalized.specialty_service_class is None and normalized.surface_kind == "landing" and (
            request.surface.startswith("website") or "local" in request.surface or request.layout_mode == "homepage"
        ):
            scored = ranked_anchors
            top_total = scored[0].score.total if scored else 0
            tied = [
                f"{item.record.manifest.pack_id}={item.score.total}"
                for item in scored
                if item.score.total == top_total
            ][:8]
            logger.warning(
                "design router unrouted: vertical=None for website/local-service request; "
                "top tied anchors: %s; picked=%s; task_preview=%r",
                ", ".join(tied) if tied else "(none)",
                anchor.record.manifest.pack_id,
                (request.task or "")[:160],
            )
        hero_record = self._pick_hero_reference_record(anchor, normalized)
        support = self._pick_support_bank(request, normalized)
        selected_examples, starvation_meta = self._pick_support_examples(request, normalized, anchor.record, hero_record, support.record if support else None)

        effective_mode = self.rules.resolve_token_mode(request.token_mode, request.local_model_profile)
        include_full = True
        max_code_chars = None
        max_atoms = None
        selected_shared_atoms = self._select_shared_atoms(
            request,
            normalized,
            anchor.record,
            mode=effective_mode,
        )
        (
            optional_patterns,
            auxiliary_anchor_packs,
            optional_pattern_catalog,
            optional_pattern_candidates,
            optional_pattern_meta,
        ) = self._pick_optional_patterns(
            request,
            normalized,
            ranked_anchors=ranked_anchors,
            anchor_record=anchor.record,
            hero_record=hero_record,
            support_record=support.record if support else None,
            selected_examples=selected_examples,
            mode=effective_mode,
            max_code_chars=max_code_chars,
            max_atoms=max_atoms,
            shared_atoms=selected_shared_atoms,
        )

        # Carry the complete selected implementation by default. Relevance chooses the
        # source; packet capacity never clips it. Stale sibling stylesheets remain
        # excluded when the primary HTML is demonstrably self-contained.
        anchor_full_source: list[dict[str, Any]] = []
        if include_full:
            pack_dir = anchor.record.pack_dir
            paths = list(anchor.record.manifest.source_paths)
            texts: dict[str, str] = {}
            for rel in paths:
                fp = pack_dir / rel
                if fp.is_file():
                    try:
                        texts[rel] = fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
            html_rels = [rel for rel in texts if rel.endswith(".html")]
            primary_html = next((rel for rel in html_rels if rel.endswith("index.html")), html_rels[0] if html_rels else None)
            # self-contained = inline <style> present and no local stylesheet link -> sibling css is stale
            self_contained = False
            if primary_html:
                head = texts[primary_html]
                self_contained = ("<style" in head) and ('rel="stylesheet"' not in head and "rel='stylesheet'" not in head)
            for rel, text in texts.items():
                if self_contained and rel != primary_html:
                    continue
                anchor_full_source.append({"path": rel, "chars": len(text), "text": text})

        anchor_pack = self.store.get_pack(anchor.record.manifest.pack_id, include_full=include_full, max_code_chars=max_code_chars, max_atoms=max_atoms)
        hero_pack = None
        if hero_record is not None:
            hero_pack = self.store.get_pack(hero_record.manifest.pack_id, include_full=include_full, max_code_chars=max_code_chars, max_atoms=max_atoms)
        support_pack = None
        if support is not None:
            support_pack = self.store.get_pack(
                support.record.manifest.pack_id,
                selected_examples=[selection.example_id for selection in selected_examples],
                include_full=include_full,
                max_code_chars=max_code_chars,
                max_atoms=max_atoms,
            )

        return RouteResolution(
            request=request,
            normalized_request=normalized,
            anchor_pack=anchor_pack,
            hero_reference_pack=hero_pack,
            support_bank=support_pack,
            selected_examples=selected_examples,
            optional_patterns=optional_patterns,
            optional_pattern_catalog=optional_pattern_catalog,
            optional_pattern_candidates=optional_pattern_candidates,
            auxiliary_anchor_packs=auxiliary_anchor_packs,
            shared_atoms=selected_shared_atoms,
            anchor_score=anchor.score,
            support_bank_score=support.score if support else None,
            route_meta={
                "trace_id": _route_trace_id(request, rules_version=self.rules.version),
                "rules_version": self.rules.version,
                "vertical": normalized.specialty_service_class,
                "donor_first": self._effective_donor_first(request, normalized),
                "lazy_loaded": True,
                "include_full_code": include_full,
                "capacity_policy": "unbounded",
                "donor_starvation": starvation_meta,
                "mechanical_donor_ids": [selection.example_id for selection in selected_examples if selection.ux_role_match],
                "candidate_gate": candidate_gate,
                "route_confidence": route_confidence(ranked_anchors, normalized, request, self.rules),
                "anchor_alternatives": anchor_alternatives,
                "anchor_full_source": anchor_full_source,
                "optional_pattern_pool": optional_pattern_meta,
                "source_selection": {
                    "requested_roles": self._priority_request_roles(request, normalized),
                    "anchor_covered_roles": sorted(self._anchor_covered_roles(anchor.record)),
                    "anchor_self_sufficient": self._anchor_is_self_sufficient(
                        request,
                        normalized,
                        anchor.record,
                    ),
                    "support_examples": [
                        selection.example_id for selection in selected_examples
                    ],
                    "shared_atoms": [
                        atom.atom_id for atom in selected_shared_atoms
                    ],
                    "optional_patterns": [
                        pattern.pattern_id for pattern in optional_patterns
                    ],
                },
            },
        )
