from __future__ import annotations

import os
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .schemas import LocalModelProfile, TokenMode


class TokenBudget(BaseModel):
    max_packet_tokens: int | None = None
    max_examples: int | None = None
    max_snippets: int | None = None
    full_code_allowed: bool = True


class NegativeExclusion(BaseModel):
    motif: list[str] = Field(default_factory=list)
    strength: list[str] = Field(default_factory=list)


class TagExpansion(BaseModel):
    motif: list[str] = Field(default_factory=list)
    strength: list[str] = Field(default_factory=list)


class TaskArchetypeRule(BaseModel):
    priority: int = 100
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    preferred_families: list[str] = Field(default_factory=list)
    preferred_pack_ids: dict[str, int] = Field(default_factory=dict)
    pack_signatures: dict[str, list[str]] = Field(default_factory=dict)
    clarify_without_signature: bool = False
    supersedes: list[str] = Field(default_factory=list)
    required_any_motifs: list[str] = Field(default_factory=list)
    blocked_families: list[str] = Field(default_factory=list)
    minimum_keyword_matches: int = Field(default=1, ge=1)

    @property
    def all_keywords(self) -> set[str]:
        return {token.lower() for token in [*self.keywords, *self.aliases]}


class VerticalRule(BaseModel):
    priority: int = 100
    keywords: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    motif_tags: list[str] = Field(default_factory=list)
    strength_tags: list[str] = Field(default_factory=list)
    prefer_tones: list[str] = Field(default_factory=list)
    preferred_anchor_pack_ids: dict[str, int] = Field(default_factory=dict)
    penalized_anchor_pack_ids: dict[str, int] = Field(default_factory=dict)
    hero_reference_pack_ids: list[str] = Field(default_factory=list)
    prefer_example_tokens: list[str] = Field(default_factory=list)
    blocked_example_tokens: list[str] = Field(default_factory=list)
    auto_donor_first: bool = False
    support_role: str = ""
    section_plan: list[str] = Field(default_factory=list)
    visual_direction: list[str] = Field(default_factory=list)
    claim_guardrails: list[str] = Field(default_factory=list)
    reject_patterns: list[str] = Field(default_factory=list)
    ux_role_fallback: list[str] = Field(default_factory=list)

    @property
    def all_keywords(self) -> set[str]:
        return {token.lower() for token in [*self.keywords, *self.aliases]}


class RoutingRules(BaseModel):
    version: str = "2.0"
    weights: dict[str, int] = Field(default_factory=dict)
    token_modes: dict[str, TokenBudget] = Field(default_factory=dict)
    profile_defaults: dict[str, str] = Field(default_factory=dict)
    expansion_order: list[str] = Field(default_factory=list)
    motif_keywords: dict[str, list[str]] = Field(default_factory=dict)
    strength_keywords: dict[str, list[str]] = Field(default_factory=dict)
    negative_style_exclusions: dict[str, NegativeExclusion] = Field(default_factory=dict)
    preference_keywords: dict[str, list[str]] = Field(default_factory=dict)
    preference_tag_expansions: dict[str, TagExpansion] = Field(default_factory=dict)
    donor_first_support_bank_ids: list[str] = Field(default_factory=list)
    generic_example_stop_tokens: list[str] = Field(default_factory=list)
    artifact_vocabularies: list[str] = Field(default_factory=list)
    composition_recipes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    task_archetypes: dict[str, TaskArchetypeRule] = Field(default_factory=dict)
    verticals: dict[str, VerticalRule] = Field(default_factory=dict)

    def token_budget(self, mode: TokenMode | str) -> TokenBudget:
        key = str(mode)
        if key not in self.token_modes:
            raise ValueError(f"Unknown token_mode '{key}'. Available: {', '.join(sorted(self.token_modes))}")
        return self.token_modes[key]

    def resolve_token_mode(self, token_mode: TokenMode | str | None, profile: LocalModelProfile | str | None) -> str:
        if token_mode:
            return str(token_mode)
        if profile:
            return self.profile_defaults.get(str(profile), "unbounded")
        return "unbounded"

    def next_expansion(self, current: TokenMode | str) -> str | None:
        if not self.expansion_order:
            return None
        try:
            idx = self.expansion_order.index(str(current))
        except ValueError:
            return None
        if idx + 1 >= len(self.expansion_order):
            return None
        return self.expansion_order[idx + 1]

    def previous_modes(self, target: TokenMode | str) -> list[str]:
        target = str(target)
        if target not in self.expansion_order:
            return []
        return self.expansion_order[: self.expansion_order.index(target)]

    def to_public_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data.pop("motif_keywords", None)
        data.pop("strength_keywords", None)
        return data


def _default_rules_path() -> Path:
    return Path(str(files("design_router_mcp") / "defaults" / "routing_rules.default.json"))


def _candidate_rule_paths(repo_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    env = os.getenv("DESIGN_ROUTER_RULES")
    if env:
        candidates.append(Path(env).expanduser())
    if repo_root is not None:
        candidates.extend(
            [
                repo_root / "design_router_rules.json",
                repo_root / "routing_rules.json",
                repo_root / "goldensets" / "routing_rules.json",
                repo_root / "src" / "design_router_mcp" / "goldensets" / "routing_rules.json",
            ]
        )
    candidates.append(_default_rules_path())
    return candidates


@lru_cache(maxsize=16)
def load_routing_rules_cached(repo_root_str: str | None = None, explicit_rules_path: str | None = None) -> RoutingRules:
    repo_root = Path(repo_root_str).expanduser().resolve() if repo_root_str else None
    if explicit_rules_path:
        path = Path(explicit_rules_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Routing rules file not found: {path}")
        return RoutingRules.model_validate_json(path.read_text(encoding="utf-8"))

    for candidate in _candidate_rule_paths(repo_root):
        try:
            path = candidate.expanduser().resolve()
        except OSError:
            path = candidate
        if path.exists():
            return RoutingRules.model_validate_json(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("No routing rules file found, including packaged default rules.")


def load_routing_rules(repo_root: Path | str | None = None, explicit_rules_path: Path | str | None = None) -> RoutingRules:
    repo = str(Path(repo_root).expanduser().resolve()) if repo_root is not None else None
    rules_path = str(Path(explicit_rules_path).expanduser().resolve()) if explicit_rules_path is not None else None
    return load_routing_rules_cached(repo, rules_path)
