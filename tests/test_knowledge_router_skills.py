"""Method-skill channel tests for the Golden Book knowledge router.

The skill channel is OPTIONAL garnish: it must never change which playbooks are
picked, never flip an abstain decision, and must render correctly per mode.
These tests guard those invariants, plus the v2 layers that touch this file's
territory (thesaurus expansion, confidence, semantic re-rank health).
"""
import json

import pytest

from design_router_mcp.knowledge_router import KnowledgeRouter, default_root, validate_knowledge_router

CORPUS_ROOT = default_root()

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / "playbooks").is_dir()
    or not (CORPUS_ROOT / "skills").is_dir()
    or not (CORPUS_ROOT / "bench" / "BRIEFS.jsonl").is_file(),
    reason=f"Golden Book corpus (with skills/) not present at {CORPUS_ROOT}",
)

B27_BRIEF = (
    "Our agent browses the web and reads emails. "
    "Design its defenses before we let it act on what it reads."
)
B09_BRIEF = (
    "Design the REST resources for a project-management tool: projects, tasks, "
    "task comments, and an archive action. Give paths, methods, and naming."
)
NONSENSE_BRIEF = "purple elephant sandwich orchestra"

# Which playbooks each brief picked BEFORE the skill channel existed, by NAME.
# Names, not scores: absolute scores legitimately drift as the corpus grows
# (24 -> 35 playbooks since this invariant was first frozen), so pinning
# floats would test corpus size, not skill-channel non-interference.
PRE_SKILL_PLAYBOOK_PICKS = {
    B27_BRIEF: (["llm-security-and-injection", "rag-and-retrieval-design"], None),
    B09_BRIEF: (["rest-api-resource-design", "incident-response-and-postmortems"], None),
    NONSENSE_BRIEF: ([], True),
}


@pytest.fixture(scope="module")
def router() -> KnowledgeRouter:
    return KnowledgeRouter()


# (a) — every skill loads as a separate channel, and the parsed-meta table
# stays in lockstep. 98 = the 2026-07-05 corpus (58 originals + 8 doctrine
# skills + 30 business skills + senior-answer-shape + gui-agent-evidence-gate);
# update the number when the corpus grows, the lockstep assertion is the part
# that must never move.
def test_skill_channel_loads_all_skills(router):
    assert len(router.skill_docs) == 98
    assert len(router._skill_meta) == len(router.skill_docs)


# (b) — playbook picks and abstain are unchanged by the skill channel, across
# three representative briefs including the nonsense-abstain one. The semantic
# re-rank is a SEPARATE layer that deliberately reorders picks by meaning, so
# it is disabled here — this invariant is skill channel vs lexical channel.
@pytest.mark.parametrize("brief", list(PRE_SKILL_PLAYBOOK_PICKS))
def test_skill_channel_does_not_disturb_playbook_picks_or_abstain(router, brief, monkeypatch):
    monkeypatch.setattr(router, "_emb", {})
    result = router.route(brief, k=2)
    expected_names, expected_abstain = PRE_SKILL_PLAYBOOK_PICKS[brief]
    assert [name for name, _ in result["picks"]] == expected_names, (
        f"playbook picks changed for {brief!r}")
    assert result.get("abstain") == expected_abstain, f"abstain flipped for {brief!r}"


# (c) — a brief that should pick a skill does. b27 (agent reads untrusted web +
# email) unambiguously warrants prompt-injection-defense.
def test_brief_that_warrants_a_skill_gets_it(router):
    result = router.route(B27_BRIEF, k=2)
    names = [n for n, _ in result["skill_picks"]]
    assert "prompt-injection-defense" in names


# A pure API-shape brief gets NO skill garnish (skills are optional).
def test_api_shape_brief_gets_no_skill(router):
    result = router.route(B09_BRIEF, k=2)
    assert result["skill_picks"] == []


def test_skill_picks_never_exceed_two(router):
    lines = (CORPUS_ROOT / "bench" / "BRIEFS.jsonl").read_text(encoding="utf-8").splitlines()
    for b in map(json.loads, filter(None, lines)):
        result = router.route(b["brief"], k=2)
        assert len(result["skill_picks"]) <= 2, f"{b['id']}: >2 skill picks"


# (d) — in micro mode a picked skill contributes only H1 + framing + pointer,
# never its procedural body (which uses `## N.` headings).
def test_micro_mode_skill_is_h1_framing_pointer_only(router):
    packet = router.resolve(B27_BRIEF, mode="micro", k=2)["packet"]
    assert "## Method skills" in packet
    assert "Full skill: skills/prompt-injection-defense.md" in packet
    skill_section = packet.split("## Method skills", 1)[1]
    # The prompt-injection-defense body has numbered `## 1.`-style sections; none
    # of those may leak into the micro packet.
    assert "## 1." not in skill_section
    assert "## Worked example" not in skill_section
    # Framing sentence is present (the "what this is for" paragraph).
    assert "retrieved content is DATA" in skill_section


# compact mode DOES include the full skill body (procedural sections present).
def test_compact_mode_skill_includes_full_body(router):
    packet = router.resolve(B27_BRIEF, mode="compact", k=2)["packet"]
    skill_section = packet.split("## Method skills", 1)[1]
    assert "## 1." in skill_section  # procedural section headings present


def test_abstained_brief_has_empty_packet_regardless_of_skills(router):
    resolved = router.resolve(NONSENSE_BRIEF)
    assert resolved.get("abstain") is True
    assert resolved["packet"] == ""


# (e) — determinism: identical calls yield identical results, skill_picks included.
def test_skill_channel_is_deterministic(router):
    for brief in (B27_BRIEF, B09_BRIEF, NONSENSE_BRIEF):
        first = router.resolve(brief, mode="compact", k=2)
        second = router.resolve(brief, mode="compact", k=2)
        assert first == second
        assert first["skill_picks"] == second["skill_picks"]


# (f) — validate tool reports the skill count and a canned skill route.
def test_validate_reports_skill_count_and_canned_skill_route():
    checks = validate_knowledge_router()
    assert checks["skill_count"] == 98
    assert checks["canned_skill_routes"] is True
    assert checks["all_pass"] is True


# ============================================================================
# v2 layer tests (Fable, 2026-07-05)


# The framing header must lead the packet, ahead of playbook content and the
# "## Method skills" section — and neither feature may disturb the other.
def test_header_precedes_playbook_and_skill_sections(router):
    packet = router.resolve(B27_BRIEF, mode="compact", k=2)["packet"]
    assert packet.startswith("Routed topics (")
    frame_at = packet.find("REFERENCE MATERIAL")
    skills_at = packet.find("## Method skills")
    assert frame_at != -1
    assert skills_at == -1 or frame_at < skills_at


# NOTE: thesaurus expansion is probed in test_knowledge_router.py on a
# synthetic corpus + synthetic thesaurus.json. A live-corpus differential
# probe was tried first and every candidate was dead on arrival — either the
# brief's context words already routed the target bare, or the single
# injected canonical couldn't out-vote them. The live-corpus effect of the
# real thesaurus is what the bench ladder measures.


# Confidence: always in [0,1]; a sharp on-topic brief must out-confidence a
# thin vague one (the coverage factor is what keeps a 2-token brief from
# reading as high-confidence off a lucky token).
def test_confidence_orders_sharp_above_vague(router):
    sharp = router.route(
        "prevent cross-site request forgery on our session cookie web app", k=2)
    vague = router.route("help me with this thing", k=2)
    for result in (sharp, vague):
        assert 0.0 <= result.get("confidence", 0.0) <= 1.0
    assert sharp.get("confidence", 0.0) > vague.get("confidence", 1.0)


# Semantic layer on the live corpus: deterministic when active (frozen corpus
# vectors + nomic-embed's stable query vectors), pure-lexical when disabled.
def test_semantic_layer_deterministic_and_optional(router, monkeypatch):
    if not router._emb:
        pytest.skip("no embeddings.json — router already in pure-lexical mode")
    brief = ("our server fetches whatever URL the customer pastes into the "
             "form; what could an attacker reach with that")
    assert router.route(brief, k=2)["picks"] == router.route(brief, k=2)["picks"]
    monkeypatch.setattr(router, "_emb", {})
    lexical = router.route(brief, k=2)
    assert "picks" in lexical  # no crash, routing still functions lexically
