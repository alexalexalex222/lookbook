import json
import re
from pathlib import Path

import pytest

from design_router_mcp import knowledge_router
from design_router_mcp.knowledge_router import KnowledgeRouter, default_root, evaluate, validate_knowledge_router

CORPUS_ROOT = default_root()

pytestmark = pytest.mark.skipif(
    not (CORPUS_ROOT / "playbooks").is_dir() or not (CORPUS_ROOT / "bench" / "BRIEFS.jsonl").is_file(),
    reason=f"Golden Book corpus not present at {CORPUS_ROOT}",
)

B27_BRIEF = (
    "Our agent browses the web and reads emails. "
    "Design its defenses before we let it act on what it reads."
)
NONSENSE_BRIEF = "purple elephant sandwich orchestra"


@pytest.fixture(scope="module")
def router() -> KnowledgeRouter:
    return KnowledgeRouter()


@pytest.fixture(scope="module")
def briefs_by_id() -> dict[str, dict]:
    lines = (CORPUS_ROOT / "bench" / "BRIEFS.jsonl").read_text(encoding="utf-8").splitlines()
    return {b["id"]: b for b in map(json.loads, filter(None, lines))}


def test_eval_hit_at_2_does_not_regress_v0(router):
    report = evaluate(k=2)
    assert report["with_expected"] == 38
    # v0's number on the frozen 38-brief benchmark; the v1 upgrades must not regress it.
    assert report["hitk"] >= 28, f"hit@2 regressed: {report['hitk']}/38 (v0 baseline 28/38)"


@pytest.mark.parametrize("brief_id", ["b18", "b35"])
def test_no_playbook_briefs_abstain_or_stay_lane_consistent(router, briefs_by_id, brief_id):
    brief = briefs_by_id[brief_id]
    result = router.route(brief["brief"], k=2)
    if result.get("abstain"):
        assert not result["picks"]
        assert result["reason"]
        return
    # Force-routing hurt on these briefs (BENCH_REPORT_V2); if the router does
    # route, every pick must at least stay in the brief's lane.
    assert result["picks"]
    for name, _score in result["picks"]:
        assert router.lanes[name] == brief["lane"], (
            f"{brief_id}: cross-lane pick {name} ({router.lanes[name]}) for a {brief['lane']} brief"
        )


def test_lane_guard_blocks_b27_orthogonal_misroute(router):
    result = router.route(B27_BRIEF, k=2)
    assert not result.get("abstain"), "b27 has a correct playbook home; it must route, not abstain"
    assert result["picks"]
    for name, _score in result["picks"]:
        assert router.lanes[name] != "backend", (
            f"b27-class misroute: security/agent brief received backend-lane playbook {name}"
        )


def test_abstain_on_nonsense_brief(router):
    result = router.route(NONSENSE_BRIEF, k=2)
    assert result.get("abstain") is True
    assert result["picks"] == []
    assert result["reason"]
    resolved = router.resolve(NONSENSE_BRIEF)
    assert resolved["packet"] == ""


def test_route_is_deterministic(router):
    for brief in (B27_BRIEF, NONSENSE_BRIEF, "Design the retry policy for a payment service."):
        first = router.resolve(brief, mode="compact", k=2)
        second = router.resolve(brief, mode="compact", k=2)
        assert first == second


def test_modes_and_packet_assembly(router):
    micro = router.resolve(B27_BRIEF, mode="micro", k=1)["packet"]
    compact = router.resolve(B27_BRIEF, mode="compact", k=1)["packet"]
    assert micro and compact
    assert len(compact) > len(micro)
    with pytest.raises(ValueError):
        router.resolve(B27_BRIEF, mode="jumbo")


def test_validate_knowledge_router_payload():
    checks = validate_knowledge_router()
    assert checks["corpus_root_exists"] is True
    assert checks["router_loads"] is True
    assert checks["playbook_count"] > 0
    assert checks["micro_count"] > 0
    assert checks["canned_brief_routes"] is True
    assert checks["nonsense_brief_abstains"] is True
    assert checks["operating_rules_loaded"] is True
    assert checks["all_pass"] is True


def test_operating_rules_ride_every_packet(router):
    # The always-on safe-execution frame: present in every mode, right after
    # the header, independent of what was routed — and still absent from
    # abstained resolves (an empty packet stays empty).
    for mode in ("micro", "compact"):
        packet = router.resolve(B27_BRIEF, mode=mode, k=1)["packet"]
        assert "Operating rules (always in effect)" in packet
        assert packet.find("Routed topics (") < packet.find("Operating rules (always in effect)")
    assert router.resolve(NONSENSE_BRIEF)["packet"] == ""


def test_operating_rules_missing_file_is_graceful(tmp_path):
    # Synthetic corpora carry no OPERATING_RULES.md: the packet must simply
    # omit the section (validate flags the absence; assembly never breaks).
    router = _matching_router(tmp_path)
    packet = router.resolve(_PLAIN_BRIEF, mode="compact", k=1)["packet"]
    assert "Operating rules" not in packet
    assert packet.startswith("Routed topics (")


def test_mcp_server_registers_knowledge_tools():
    import asyncio

    from design_router_mcp import mcp_server

    try:
        server = mcp_server.create_mcp_server(Path(__file__).resolve().parents[1])
    except mcp_server.MissingMcpDependencyError:
        pytest.skip("optional mcp dependency not installed")
    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "resolve_knowledge_context" in tool_names
    assert "validate_knowledge_router" in tool_names
    # existing design tools must be untouched
    assert "resolve_design_context" in tool_names
    assert "validate_design_router" in tool_names


def test_knowledge_route_telemetry_appends_events(tmp_path, monkeypatch):
    # The serving layer appends one JSONL event per knowledge route — the
    # corpus's content flywheel. Pointed at tmp via GOLDENBOOK_ROOT so the
    # real ledger is untouched; the helper must never raise into serving.
    from design_router_mcp.mcp_server import log_knowledge_route

    monkeypatch.setenv("GOLDENBOOK_ROOT", str(tmp_path))
    routed = {"picks": [("demo-topic", 0.51)], "skill_picks": [], "confidence": 0.42,
              "top5": [("demo-topic", 0.51)], "lane_inference": {"semantic_reranked": True}}
    log_knowledge_route(routed, "a routed brief", "compact", 2, "")
    abstained = {"abstain": True, "reason": "no lexical match: best 0.01",
                 "picks": [], "skill_picks": [], "top5": [("near-a", 0.05)], "lane_inference": {}}
    log_knowledge_route(abstained, "an off-book brief", "micro", 1, "raw user text")
    lines = (tmp_path / "telemetry" / "ROUTES.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first, second = map(json.loads, lines)
    assert first["abstain"] is False and first["picks"] == [["demo-topic", 0.51]]
    assert first["semantic_reranked"] is True and first["user_message_supplied"] is False
    assert second["abstain"] is True and second["user_message_supplied"] is True
    assert second["closest_topics"] == [["near-a", 0.05]]


# ============================================================================
# v2 improvement-layer tests (Fable, 2026-07-05).
#
# Everything below runs on SYNTHETIC corpora under tmp_path. The live corpus
# keeps growing, and a probe that asserts preconditions about its score
# distribution is a landmine waiting for the next playbook batch — so each
# probe builds a corpus whose scores it controls exactly, and the two floor
# gates are tested with each other disabled (one mechanism per probe).
# Synthetic corpora carry no thesaurus.json / embeddings.json, so expansion
# and the semantic layer are naturally OFF unless a test injects them.

# Twenty vocabulary words for controlled overlap. None are STOP words, all
# survive tokens() (len > 2), and none collide with any synthetic doc name.
_VOCAB = ("crank flywheel gasket piston camshaft rotor solenoid manifold "
          "turbine bearing sprag detent pawl cam yoke spool poppet orifice "
          "plenum shroud").split()


def _mk_corpus(root: Path, docs: dict[str, str],
               sources: dict[str, list[str]] | None = None) -> None:
    """Minimal Golden Book shape: playbooks/<name>.md with optional Sources.

    At least two vocabulary-disjoint docs are always supplied by callers:
    in a one-doc corpus every token has document frequency == corpus size,
    idf collapses to zero, and every score is 0.
    """
    (root / "playbooks").mkdir(parents=True, exist_ok=True)
    for name, body in docs.items():
        text = f"---\ntitle: {name}\n---\n# {name}\n\n{body}\n\n## Sources\n"
        for rel in (sources or {}).get(name, ()):
            text += f"- {rel}\n"
        (root / "playbooks" / f"{name}.md").write_text(text, encoding="utf-8")


# --- floor probes -----------------------------------------------------------
# Three docs with engineered overlap against a 20-token brief:
#   floor-alpha  all 20 tokens   -> score 1.0
#   floor-bravo  16 of 20        -> score ~0.586
#   floor-charlie 8 of 20        -> score ~0.172
# plus a disjoint decoy so idf stays informative. Scores are deterministic
# functions of the overlap counts; the assertions below only need their
# ORDER and rough separation, never exact values.

_FLOOR_BRIEF = " ".join(_VOCAB)


def _floors_router(tmp_path: Path) -> KnowledgeRouter:
    _mk_corpus(tmp_path, {
        "floor-alpha": " ".join(_VOCAB),
        "floor-bravo": " ".join(_VOCAB[:16]),
        "floor-charlie": " ".join(_VOCAB[:8]),
        "floor-decoy": "meadow willow brook fern moss lichen",
    })
    return KnowledgeRouter(tmp_path)


def test_min_score_floor_cuts_a_trailing_pick(tmp_path, monkeypatch):
    router = _floors_router(tmp_path)
    # Ratio rule disabled: this probe pins MIN_SCORE and nothing else.
    monkeypatch.setattr(knowledge_router, "SECOND_PICK_RATIO", 0.0)
    open_picks = [n for n, _ in router.route(_FLOOR_BRIEF, k=3)["picks"]]
    assert open_picks == ["floor-alpha", "floor-bravo", "floor-charlie"]
    # Raise the floor between bravo (~0.59) and charlie (~0.17): charlie out.
    monkeypatch.setattr(knowledge_router, "MIN_SCORE", 0.3)
    floored = [n for n, _ in router.route(_FLOOR_BRIEF, k=3)["picks"]]
    assert floored == ["floor-alpha", "floor-bravo"]


def test_second_pick_ratio_cuts_a_trailing_pick(tmp_path, monkeypatch):
    router = _floors_router(tmp_path)
    # bravo (~0.59) survives the default 0.5 ratio against alpha (1.0)...
    assert [n for n, _ in router.route(_FLOOR_BRIEF, k=2)["picks"]] == \
        ["floor-alpha", "floor-bravo"]
    # ...and is cut once the required fraction moves above its share.
    monkeypatch.setattr(knowledge_router, "SECOND_PICK_RATIO", 0.7)
    assert [n for n, _ in router.route(_FLOOR_BRIEF, k=2)["picks"]] == ["floor-alpha"]


def test_relevance_floor_abstain_branch_is_live(tmp_path, monkeypatch):
    # Under shipped constants this branch is shadowed (MIN_SCORE 0.06 sits
    # below HARD_FLOOR 0.10, so any brief that survives the abstain gates has
    # a pick above the floor). Prove the guard is live code anyway: with the
    # floor above every score, the picks loop must abstain, not crash.
    router = _floors_router(tmp_path)
    monkeypatch.setattr(knowledge_router, "MIN_SCORE", 2.0)
    result = router.route(_FLOOR_BRIEF, k=2)
    assert result.get("abstain") is True
    assert result["picks"] == []
    assert "relevance floor" in result["reason"]


# --- standard-mode raw-source gating ----------------------------------------

def test_standard_mode_serves_only_tier_a_unrejected_capped_at_three(tmp_path):
    _mk_corpus(tmp_path, {
        "gearbox-service-manual": " ".join(_VOCAB[:10]),
        "null-decoy-field": "meadow willow brook fern moss lichen",
    }, sources={"gearbox-service-manual": [
        "raw/src-aa.md", "raw/src-bb.md", "raw/src-cc.md",
        "raw/src-dd.md", "raw/src-ee.md", "raw/src-fb.md",
    ]})
    raw = tmp_path / "raw"
    raw.mkdir()
    for stem in ("src-aa", "src-cc", "src-dd", "src-ee"):
        (raw / f"{stem}.md").write_text(f"---\ntier: A\n---\nUsable excerpt body for {stem}.\n")
    (raw / "src-bb.md").write_text("---\ntier: A\n---\nREJECT: superseded, never cite.\n")
    (raw / "src-fb.md").write_text("---\ntier: B\n---\nSecondary-tier material.\n")

    router = KnowledgeRouter(tmp_path)
    result = router.resolve(" ".join(_VOCAB[:10]), mode="standard", k=1)
    assert [n for n, _ in result["picks"]] == ["gearbox-service-manual"]
    excerpts = [ln for ln in result["packet"].splitlines() if ln.startswith("[source excerpt:")]
    # Eligible after gating: aa, cc, dd, ee (bb is REJECTed, fb is tier B);
    # the 3-excerpt cap then drops ee. One exact list pins all three rules.
    assert excerpts == [
        "[source excerpt: raw/src-aa.md]",
        "[source excerpt: raw/src-cc.md]",
        "[source excerpt: raw/src-dd.md]",
    ]


# --- lane-guard demotion (the mechanism, with its evidence trail) ------------

def test_lane_guard_demotes_and_reports_evidence(tmp_path):
    # One agentic doc ties three backend docs on shared vocabulary and wins
    # the tie-break purely by name — but backend holds 3x the top-5 lane
    # mass, the lexical lane signal is silent (every shared token lives in
    # both lanes), and the brief carries no token of the top pick's name.
    # The guard must demote it and say so.
    shared = " ".join(_VOCAB[:10])
    _mk_corpus(tmp_path, {
        "aaa-drift-probe": shared,
        "mmm-anchor-one": shared,
        "mmm-anchor-two": shared,
        "mmm-anchor-three": shared,
        "zzz-null-field": "meadow willow brook fern moss lichen",
    }, sources={
        "aaa-drift-probe": ["raw/agentic/seed.md"],
        "mmm-anchor-one": ["raw/backend/seed.md"],
        "mmm-anchor-two": ["raw/backend/seed.md"],
        "mmm-anchor-three": ["raw/backend/seed.md"],
    })
    router = KnowledgeRouter(tmp_path)
    result = router.route(shared, k=2)
    assert not result.get("abstain")
    lane_info = result["lane_inference"]
    assert lane_info["brief_lane"] == "backend"
    assert lane_info["method"] == "top5_mass"
    assert lane_info["top_pick_lane"] == "agentic"
    assert lane_info["guard_triggered"] is True
    assert lane_info["demoted_top_pick"] == "aaa-drift-probe"
    assert lane_info["name_token_veto"] == []
    assert result["picks"]
    for name, _score in result["picks"]:
        assert router.lanes[name] == "backend"


# --- packet header + tradeoff framing ----------------------------------------

def _matching_router(tmp_path: Path) -> KnowledgeRouter:
    _mk_corpus(tmp_path, {
        "torque-spec-sheet": " ".join(_VOCAB[:6]),
        "zzz-null-field": "meadow willow brook fern moss lichen",
    })
    return KnowledgeRouter(tmp_path)


_PLAIN_BRIEF = "Explain crank flywheel gasket piston camshaft rotor calibration for the shop."


def test_packet_opens_with_framing_header(tmp_path):
    router = _matching_router(tmp_path)
    result = router.resolve(_PLAIN_BRIEF, mode="compact", k=1)
    assert not result.get("abstain")
    first, second = result["packet"].splitlines()[:2]
    assert first.startswith("Routed topics (1 pick, confidence ")
    assert result["picks"][0][0] in first
    assert "REFERENCE MATERIAL" in second


def test_tradeoff_brief_gets_the_tradeoff_line(tmp_path):
    router = _matching_router(tmp_path)
    brief = "Crank versus flywheel: justify the tradeoff for gasket piston camshaft rotor work."
    packet = router.resolve(brief, mode="compact", k=1)["packet"]
    assert "THIS BRIEF ASKS FOR AN ARGUED TRADEOFF" in packet


def test_plain_brief_has_no_tradeoff_line(tmp_path):
    router = _matching_router(tmp_path)
    packet = router.resolve(_PLAIN_BRIEF, mode="compact", k=1)["packet"]
    assert "THIS BRIEF ASKS FOR AN ARGUED TRADEOFF" not in packet


def test_should_we_is_a_choice_but_how_should_we_is_not(tmp_path):
    # "Should we switch supplier?" asks for a decision; "How should we mount
    # it?" asks for instructions. The detector must split exactly there —
    # calibrated on b26 (true positive) vs d07/d15 (false positives fixed
    # 2026-07-05).
    router = _matching_router(tmp_path)
    choice = "Should we switch the crank flywheel gasket piston camshaft rotor supplier?"
    howto = "How should we mount the crank flywheel gasket piston camshaft rotor?"
    assert "THIS BRIEF ASKS FOR AN ARGUED TRADEOFF" in \
        router.resolve(choice, mode="compact", k=1)["packet"]
    assert "THIS BRIEF ASKS FOR AN ARGUED TRADEOFF" not in \
        router.resolve(howto, mode="compact", k=1)["packet"]


def test_abstained_resolve_has_no_header(tmp_path):
    router = _matching_router(tmp_path)
    result = router.resolve(NONSENSE_BRIEF, mode="compact", k=1)
    assert result.get("abstain") is True
    assert result["packet"] == ""


# --- user_message augment -----------------------------------------------------

_WEAK_BRIEF = "help me sort this out"


def test_user_message_recovers_a_brief_that_abstains_alone(tmp_path):
    router = _matching_router(tmp_path)
    alone = router.route(_WEAK_BRIEF, k=1)
    assert alone.get("abstain") is True, "a lossy summary alone must abstain here"
    augmented = router.route(_WEAK_BRIEF, k=1, user_message=_PLAIN_BRIEF)
    assert not augmented.get("abstain")
    assert augmented["picks"][0][0] == "torque-spec-sheet", (
        "with the raw user text folded in, routing must land on what the user said"
    )


def test_empty_user_message_is_byte_identical(router):
    for brief in (B27_BRIEF, NONSENSE_BRIEF, "Design the retry policy for a payment service."):
        assert router.route(brief, k=2) == router.route(brief, k=2, user_message="")
        assert router.resolve(brief, k=2) == router.resolve(brief, k=2, user_message="")


def test_header_confidence_agrees_with_result_confidence(tmp_path):
    # Confidence is computed once in route() on the FULL token bag and
    # threaded through to the header. Recomputing it in the header from the
    # brief alone (the pre-redo behavior) disagrees exactly when user_message
    # contributed tokens — this pins the single-computation contract.
    router = _matching_router(tmp_path)
    result = router.resolve(_WEAK_BRIEF, mode="compact", k=1, user_message=_PLAIN_BRIEF)
    assert not result.get("abstain")
    header_conf = re.search(r"confidence (\d\.\d\d)\)", result["packet"].splitlines()[0])
    assert header_conf, "header must render a confidence"
    assert header_conf.group(1) == f"{result['confidence']:.2f}"


# --- abstain retry guide + packet use contract ---------------------------------

def test_summarized_audit_brief_routes_and_abstains_still_teach(router):
    # Day-one live regression, both halves. (1) The agent-summarized browser
    # audit brief that originally ABSTAINED (checklist nouns stripped the
    # routing vocabulary) now routes to the CUA chapter outright — the
    # chapter's state-space sections closed the vocabulary gap at the source;
    # pin that against backsliding. (2) Abstains still teach the second call:
    # a no-footing brief returns a retry_guide carrying the user_message move.
    summary = ("QA audit of a live production website foldops.com — read-only browser "
               "audit checking every page, nav link, button, interactive element, broken "
               "links, layout overflow at 390px mobile width, console errors, and slow "
               "assets. No form submissions, no bookings, no state changes.")
    result = router.route(summary, k=2)
    assert not result.get("abstain"), "the day-one regression brief must route now"
    assert result["picks"][0][0] == "browser-automation-and-computer-use"

    hard = router.route(NONSENSE_BRIEF, k=2)
    assert hard.get("abstain") is True
    guide = hard["retry_guide"]
    assert guide["closest_topics"] == []  # nothing ranked above zero
    assert any("user_message" in step for step in guide["how_to_retry"])


def test_retry_guide_survives_bare_corpora(tmp_path, monkeypatch):
    # Synthetic corpus: no scenarios.json — symptoms degrade to "" and the
    # guide still forms; a floor forced above every score exercises the
    # relevance-floor abstain path carrying the guide too.
    router = _floors_router(tmp_path)
    monkeypatch.setattr(knowledge_router, "MIN_SCORE", 2.0)
    result = router.route(_FLOOR_BRIEF, k=2)
    assert result.get("abstain") is True
    guide = result["retry_guide"]
    assert guide["closest_topics"][0]["topic"] == "floor-alpha"
    assert guide["closest_topics"][0]["symptom"] == ""
    assert guide["how_to_retry"]


def test_packet_header_carries_use_contract(router):
    packet = router.resolve(B27_BRIEF, mode="micro", k=1)["packet"]
    assert "USE CONTRACT" in packet.splitlines()[2], (
        "the engagement contract rides line 3 of every packet header")


# --- thesaurus expansion ------------------------------------------------------

def test_thesaurus_expansion_routes_a_synonym_only_brief(tmp_path, monkeypatch):
    # Synthetic corpus + synthetic thesaurus.json, so the synonym is the ONLY
    # informative token in the brief and expansion alone decides the route.
    # (Live-corpus differential probes are unfixably noisy: context words
    # either pre-route the target or out-vote a single injected canonical.)
    # This exercises the real path end-to-end: file -> reverse index ->
    # brief-side expansion -> scoring.
    _mk_corpus(tmp_path, {
        "rotor-balancing": "rotor balancing shaft counterweight vibration harmonics",
        "brook-mapping": "brook mapping meadow willow fern",
    })
    (tmp_path / "thesaurus.json").write_text(json.dumps({"map": {
        "rotor-balancing": ["spinfix", "wobblefix"],
        "brook-mapping": ["wobblefix"],
    }}), encoding="utf-8")
    router = KnowledgeRouter(tmp_path)

    # Loader contract: canonical maps to itself plus its hyphen-split words;
    # a synonym claimed by two concepts accumulates both.
    assert {"rotor-balancing", "rotor", "balancing"} <= set(router._syn2canon["spinfix"])
    assert {"rotor", "brook"} <= set(router._syn2canon["wobblefix"])

    brief = "calibrate the spinfix rig"
    monkeypatch.setattr(router, "_syn2canon", {})
    assert router.route(brief, k=2).get("abstain") is True, (
        "without expansion the synonym is an unknown token and the brief must abstain")
    monkeypatch.undo()
    expanded = router.route(brief, k=2)
    assert not expanded.get("abstain")
    assert [n for n, _ in expanded["picks"]] == ["rotor-balancing"]


# --- semantic re-rank: qualified pool only ------------------------------------

def test_semantic_rescue_at_weak_flat_gate_only(tmp_path, monkeypatch):
    # Three docs each hold two of the brief's ten tokens, so every score is a
    # flat 0.2 — below SOFT_FLOOR, above HARD_FLOOR: the weak-and-flat gate
    # fires. With a query embedding decisively close to one qualified doc the
    # route must proceed (flagged); with all sims low it must still refuse;
    # and a no-lexical-footing brief must refuse regardless of embeddings.
    # The lanes are arranged so the guard would demote the rescued winner
    # (backend top pick, agentic lane mass) — the sim-top corroboration veto
    # must protect it: two channels agreeing is not a cross-lane accident.
    _mk_corpus(tmp_path, {
        "aaa-rescue-target": "quill spindle brace strut girder",
        "mmm-rescue-alpha": "ferrule collet brace strut girder",
        "mmm-rescue-bravo": "arbor mandrel brace strut girder",
    }, sources={
        "aaa-rescue-target": ["raw/backend/seed.md"],
        "mmm-rescue-alpha": ["raw/agentic/seed.md"],
        "mmm-rescue-bravo": ["raw/agentic/seed.md"],
    })
    router = KnowledgeRouter(tmp_path)
    brief = "quill spindle ferrule collet arbor mandrel chuck tang bevel knurl"
    assert router.route(brief, k=2).get("abstain") is True, (
        "precondition: flat 0.2 scores must abstain without the semantic layer")
    router._emb = {"model": "stub", "playbooks": {
        "aaa-rescue-target": [0.0, 0.0, 1.0],
        "mmm-rescue-alpha": [0.0, 1.0, 0.0],
        "mmm-rescue-bravo": [0.0, 1.0, 0.0],
    }}
    monkeypatch.setattr(router, "_embed_query", lambda text: [0.0, 0.0, 1.0])
    rescued = router.route(brief, k=2)
    assert not rescued.get("abstain")
    lane_info = rescued["lane_inference"]
    assert lane_info.get("semantic_rescued", 0) >= 0.99
    assert lane_info.get("sim_corroboration_veto") is True
    assert lane_info.get("guard_triggered") is False
    assert rescued["picks"][0][0] == "aaa-rescue-target"

    monkeypatch.setattr(router, "_embed_query", lambda text: [1.0, 0.0, 0.0])
    refused = router.route(brief, k=2)  # sims all 0.0 < RESCUE_SIM
    assert refused.get("abstain") is True
    assert "weak and flat" in refused["reason"]

    hard = router.route(NONSENSE_BRIEF, k=2)  # no lexical footing at all
    assert hard.get("abstain") is True
    assert "no lexical match" in hard["reason"]


def test_semantic_rerank_reorders_qualified_picks_but_admits_nothing(tmp_path, monkeypatch):
    # sem-target-uno matches the brief fully (1.0), sem-target-dos partially
    # (~0.27, above MIN_SCORE), sem-villain-tres not at all (0.0). The stub
    # embeddings make dos AND the villain maximally similar to the query.
    # Contract under test: the blend may lift dos over uno, but the villain
    # — lexically rejected — must stay out of the picks entirely, and the
    # route must not abstain. (A whole-pool re-rank would walk the villain
    # to the front, where the picks loop's floor-break abstains the brief.)
    uno_vocab = "quill spindle ferrule collet arbor mandrel chuck tang bevel knurl"
    _mk_corpus(tmp_path, {
        "sem-target-uno": uno_vocab,
        "sem-target-dos": "quill spindle ferrule collet arbor washer grommet flange bushing seal",
        "sem-villain-tres": "meadow willow brook fern moss lichen sedge reed vale heath",
    })
    router = KnowledgeRouter(tmp_path)
    router._emb = {"model": "stub", "playbooks": {
        "sem-target-uno": [1.0, 0.0],
        "sem-target-dos": [0.0, 1.0],
        "sem-villain-tres": [0.0, 1.0],
    }}
    monkeypatch.setattr(router, "_embed_query", lambda text: [0.05, 1.0])

    result = router.route(uno_vocab, k=2)
    assert not result.get("abstain")
    names = [n for n, _ in result["picks"]]
    assert "sem-villain-tres" not in names
    assert names == ["sem-target-dos", "sem-target-uno"], (
        "blend should lift the semantically-close qualified pick, keep the other"
    )
    assert result["lane_inference"].get("semantic_reranked") is True

    # Graceful fallback: embed hop dead -> pure lexical, no rerank flag.
    monkeypatch.setattr(router, "_embed_query", lambda text: None)
    lexical = router.route(uno_vocab, k=2)
    assert [n for n, _ in lexical["picks"]] == ["sem-target-uno"]
    assert "semantic_reranked" not in lexical["lane_inference"]
