"""Golden Book knowledge router v2 — canonical brief→playbook routing.

The v1 core (below) is untouched: deterministic TF-IDF selection with a LANE
GUARD and first-class ABSTAIN, calibrated on bench/BRIEFS.jsonl. v2 layers
meaning on top of that core without moving any of its decisions:

1. THESAURUS EXPANSION — thesaurus.json maps canonical concepts to the
   synonyms briefs actually use ("throttle" → rate-limiting). Expansion is
   brief-side only and purely additive: a synonym token gains its canonical
   concept token(s) so a paraphrased brief meets the corpus vocabulary. The
   doc/IDF side is never touched, so corpus statistics stay corpus-owned.

2. SEMANTIC RE-RANK — frozen corpus embeddings (embeddings.json, built
   offline by ~/goldenbook-harvest/build_embeddings.py over nomic-embed via
   local ollama) plus ONE live query embedding reorder the qualified pick
   pool by a lexical+semantic blend (SEM_ALPHA). Floors, abstain, and the
   lane guard all run BEFORE this layer on pure lexical scores, and only
   entries already above MIN_SCORE are eligible for reordering — the
   semantic layer arbitrates order among picks the lexical core accepted; it
   can never introduce one it rejected. One deliberate exception (v2.1): at
   the weak-and-flat abstain gate, a decisively high query-to-playbook
   similarity (>= RESCUE_SIM) rescues the route instead of refusing it —
   verbose realistic briefs spread lexical mass thin, and the gate used to
   refuse briefs whose correct answer already led both channels. The hard
   floor is never rescued. If embeddings.json or ollama is unavailable the
   router silently degrades to pure lexical.

3. USER-MESSAGE AUGMENT — route()/resolve() accept the raw end-user text as
   an optional second signal. A model-authored brief that summarizes the
   task badly can still route on what the user actually said. Passing "" is
   byte-identical to omitting the argument.

4. CONFIDENCE + PACKET HEADER — every non-empty packet opens with a framing
   header: the routed topics, a deterministic confidence in [0,1], a line
   telling the consumer the packet is reference material rather than a
   script, and a stronger line when the brief asks for an argued tradeoff.
   Confidence is computed once per route and never gates a pick.

5. OPERATING RULES (v2.2) — OPERATING_RULES.md at the corpus root rides
   every non-empty packet immediately after the header, in every mode: the
   always-on safe-execution frame (nothing destructive or irreversible
   unasked, sandbox before live, back up before edits, two identical
   failures = stop). Deliberately NOT routed — the safety frame must never
   depend on what the brief looked like.

The v1 core, from tools/route.py v0 plus the two upgrades motivated by
bench/BENCH_REPORT_V2.md:

1. LANE GUARD — every playbook gets a lane (agentic|backend) derived from the
   majority of its ``- raw/<lane>/...`` Sources citations (no hardcoded lists).
   The brief's lane is inferred lexically from lane-distinctive vocabulary
   (tokens whose per-lane document frequency differs by >= LANE_LEX_GATE),
   falling back to the lane-mass of the top-5 scores when the lexicon is
   silent. Lane-mass alone provably cannot fix b27-class misroutes — the
   orthogonal misroutes ARE the mass — which is why the lexical signal leads.
   When the top pick's lane contradicts the inferred brief lane by a clear
   margin, picks are restricted to the brief's lane. A name-token veto (the
   brief literally contains a token of the top pick's topic name) protects
   on-topic picks from cross-lane vocabulary in the brief (b09-class).

2. ABSTAIN — routing is refused (``abstain: true``) when the best score is
   below a hard floor, or is both weak (< SOFT_FLOOR) and flat (not clearly
   above the median of the top-5). Force-routing no-playbook briefs hurt in
   the v2 bench (b18, b35); abstaining is a first-class outcome.

Kept from v0: TF-IDF scoring with topic-name boost, second-pick margin rule
(>= half of the first pick's score), modes micro/compact/standard, and fully
deterministic behavior (ties broken by name).

Corpus root defaults to ~/goldenbook-harvest; override with the
GOLDENBOOK_ROOT environment variable or the ``root`` parameter.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import urllib.request
from pathlib import Path
from typing import Any

STOP = set("""a an and are as at be but by for from has have how if in into is
it its of on or our so that the this to we what when where which with you your
should must can could will would do does not no never always design write our
give propose today currently""".split())

# Per-pick relevance floor (v0's MIN_SCORE).
MIN_SCORE = 0.06
# Second pick must score at least this fraction of the first pick (v0 rule).
SECOND_PICK_RATIO = 0.5
# Abstain: best score below this is no lexical match at all.
HARD_FLOOR = 0.10
# Abstain: best score below SOFT_FLOOR *and* flatter than FLAT_RATIO x median
# of the top-5 means no pick stands out (b18-class).
SOFT_FLOOR = 0.28
FLAT_RATIO = 1.4
# Lane lexicon: a token counts as lane-distinctive when its per-lane doc
# frequency differs by at least this much.
LANE_LEX_GATE = 0.5
# Minimum |lexical affinity| to call the brief's lane from vocabulary alone.
LANE_LEX_MARGIN = 0.3
# Fallback: top-5 lane mass must exceed the other lane by this factor.
LANE_MASS_MARGIN = 2.0

# --- Semantic layer (v2) ----------------------------------------------------
# Blend weight: combined = SEM_ALPHA * lexical + (1 - SEM_ALPHA) * semantic.
# 0.3 was the bench-swept optimum on BRIEFS.jsonl (hit@1 25 -> 29/38). The
# lexical share looks small, but every gate upstream of the blend (floors,
# abstain, lane guard, skill admission) is pure lexical — this weight only
# arbitrates order WITHIN an already-qualified pool.
SEM_ALPHA = 0.3
# Semantic rescue at the weak-and-flat gate ONLY (v2.1). Realistic verbose
# briefs spread their lexical mass thin and used to be refused with the right
# answer already ranked #1 (a descriptive SSRF brief missed the soft floor by
# 0.007 while ssrf led both channels). If the best cosine between the query
# and any MIN_SCORE-qualified playbook clears this floor, the route proceeds
# (marked semantic_rescued) instead of abstaining. Calibrated 2026-07-05 on a
# measured corridor: off-book control briefs top out at 0.5262; genuine
# descriptive targets bottom at 0.6302 — 0.60 splits it with margin on both
# sides. The HARD floor is untouched: a brief with no lexical footing at all
# still abstains, whatever its embedding says.
RESCUE_SIM = 0.60
# Local ollama embeddings endpoint. The query embed is the only live call the
# router ever makes, and any failure of it falls back to pure lexical.
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"

# --- Method-skill channel (separate from the playbook channel) ------------
# Skills are OPTIONAL garnish scored on a deliberately shallow doc: the
# source_title subtitle is the when-clause that says which task the skill is
# for, so it is weighted heaviest; H1 is the topic name; the framing paragraph
# is the one-paragraph "what this is for". Section headings and the body-wide
# TF are DROPPED: skill bodies are procedural checklists whose vocabulary
# ("worked example", "the core rule", generic verbs) matches almost any brief
# and only adds noise. This keeps a skill's fingerprint to its intent, not its
# prose.
SKILL_SUBTITLE_WEIGHT = 6
SKILL_H1_WEIGHT = 3
# A skill is admitted only if its score clears this floor AND the brief hits at
# least SKILL_MIN_STEMS *distinct word stems* of the skill doc. Both gates were
# calibrated on bench/BRIEFS.jsonl: the floor alone lets single-high-IDF-token
# coincidences through (e.g. "workers" -> kanban-worker-fleets on a Redis-lock
# brief), and the stem-breadth gate (counting stems, so task/tasks count once)
# is what actually kills them. 0.12 keeps every genuinely useful pilot pick
# (b21/b25/b26/b27/b30/b36) while giving pure API-shape briefs (b09/b10) none.
SKILL_FLOOR = 0.12
SKILL_MIN_STEMS = 2
# At most this many skills per brief; skills are garnish, never the main packet.
SKILL_MAX_PICKS = 2

MODES = ("micro", "compact", "standard")


def _stem(token: str) -> str:
    """Cheap plural fold so task/tasks and agent/agents count as one stem.

    Deliberately minimal (no full stemmer dependency): only trailing -ies/-es/-s
    on tokens long enough that the stem stays >= 3 chars. This is used ONLY for
    the skill breadth gate, never for scoring, so precision matters more than
    recall — over-folding would merge unrelated tokens and weaken the gate.
    """
    for suf in ("ies", "es", "s"):
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            return token[: -len(suf)] + ("y" if suf == "ies" else "")
    return token


def default_root() -> Path:
    env = os.environ.get("GOLDENBOOK_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / "goldenbook-harvest"


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9-]+", text.lower())
            if w not in STOP and len(w) > 2]


def _strip_fm(text: str) -> str:
    return text.split("---", 2)[-1] if text.startswith("---") else text


def _cosine(a: list[float], b: list[float]) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


# --- Packet framing (v2) -----------------------------------------------------
# Every non-empty packet opens with a deterministic, topic-agnostic header that
# says HOW to use the packet, never what to conclude. Motivation:
# packet-dominance — a consumer model handed a strong single-stance packet
# tends to transcribe it even when the brief asked for an argued choice
# (design-router bench, b13 class). Both framing lines below are retained
# verbatim from the wording the packet-dominance re-judge validated: rewording
# them is cheap to do and expensive to re-verify, so don't touch them without
# a judge run. Nothing in this section influences scoring or picks.
_FRAME_REFERENCE = (
    "This packet is REFERENCE MATERIAL to inform your answer, not a directive "
    "to transcribe; where the brief asks you to compare/justify/choose, argue "
    "the tradeoff the brief asks for and treat any single stance here as one "
    "input."
)
_FRAME_TRADEOFF = (
    "THIS BRIEF ASKS FOR AN ARGUED TRADEOFF — present both positions "
    "before recommending."
)
# The engagement contract (v2.4, reframed v2.5): REFERENCE MATERIAL framing
# alone lets a consumer skim a 30k-char packet and answer from priors — but a
# compliance-flavored contract over-corrects: a live A/B (same model, book
# on/off) showed the packeted run stopped exploring and optimized for
# demonstrated adherence, while the bare run poked at states like a senior
# and won. FLOOR, NOT CEILING is the balance: coverage of known traps stays
# verifiable (name the sections), and judgment beyond the chapter is
# explicitly licensed.
_FRAME_CONTRACT = (
    "USE CONTRACT: the routed chapters are your FLOOR, not your ceiling — "
    "cover every trap and rule they flag (name the sections you applied), "
    "then go BEYOND them wherever your own judgment sees further. The goal "
    "is the best outcome for THIS task, never demonstrated adherence to the "
    "packet."
)
_TRADEOFF_WORDS = {"vs", "versus", "tradeoff", "trade-off", "justify", "either"}
_TRADEOFF_PHRASES = ("choose between", "which is better")


def _asks_for_tradeoff(brief: str) -> bool:
    """True when the brief lexically asks for a compared or justified choice.

    Calibrated against the fixed benches (2026-07-05): every word in
    _TRADEOFF_WORDS has a true positive there (b04/b22 "vs", as02 "versus",
    b39 plus five AppSec briefs "justify", b36 "either") and no false
    positive. "should we" needs care: "Should we split into multiple agents?"
    is a genuine choice (b26), but "how should we store passwords?" is a
    how-to (d07/d15) — so it only counts when not led by "how".
    """
    low = brief.lower()
    if any(phrase in low for phrase in _TRADEOFF_PHRASES):
        return True
    if re.search(r"(?<!\bhow )\bshould we\b", low):
        return True
    words = re.findall(r"[a-z0-9][a-z0-9-]*", low)
    return any(w in _TRADEOFF_WORDS for w in words)


class KnowledgeRouter:
    """Deterministic TF-IDF router over the Golden Book playbook corpus."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else default_root()
        self.playbooks_dir = self.root / "playbooks"
        self.micro_dir = self.playbooks_dir / "micro"
        self.skills_dir = self.root / "skills"
        self.thesaurus_path = self.root / "thesaurus.json"
        self.briefs_path = self.root / "bench" / "BRIEFS.jsonl"
        # v2 inputs, both optional: no thesaurus -> no expansion; no embeddings
        # -> pure-lexical routing. Neither may ever make construction fail.
        self._syn2canon: dict[str, list[str]] = self._load_thesaurus()
        self._emb: dict[str, Any] = self._load_embeddings()
        self._operating_rules: str = self._load_operating_rules()
        self._scenarios: dict[str, str] = self._load_scenarios()
        self.docs: dict[str, list[str]] = {}
        self.lanes: dict[str, str | None] = {}
        self.idf: dict[str, float] = {}
        self._lane_df: dict[str, dict[str, int]] = {"agentic": {}, "backend": {}}
        self._lane_n: dict[str, int] = {"agentic": 0, "backend": 0}
        # Method-skill channel: parsed intent tokens per skill (see _load_skills).
        self.skill_docs: dict[str, list[str]] = {}
        self._skill_meta: dict[str, dict[str, str]] = {}
        self._load()
        self._load_skills()

    # ------------------------------------------------------------- corpus
    def _load(self) -> None:
        if not self.playbooks_dir.is_dir():
            raise FileNotFoundError(f"Golden Book playbooks dir not found: {self.playbooks_dir}")
        for path in sorted(self.playbooks_dir.glob("*.md")):
            name = path.stem
            body = _strip_fm(path.read_text(encoding="utf-8"))
            micro = self.micro_dir / path.name
            if micro.is_file():
                body += "\n" + _strip_fm(micro.read_text(encoding="utf-8"))
            # topic-name words count extra (the name is the strongest signal)
            self.docs[name] = tokens(body) + tokens(name.replace("-", " ")) * 8
            self.lanes[name] = self._derive_lane(path)
        n = len(self.docs)
        df: dict[str, int] = {}
        for name, toks in self.docs.items():
            lane = self.lanes[name]
            if lane:
                self._lane_n[lane] += 1
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
                if lane:
                    self._lane_df[lane][t] = self._lane_df[lane].get(t, 0) + 1
        # IDF is deliberately PLAYBOOK-ONLY. Folding the skill docs into df was
        # tried on 2026-07-04 and REVERTED by the bench (hit@2 29 -> 28, AppSec
        # 7/7 -> 5/6): skill docs are deliberately shallow, so letting them
        # vote df makes domain terms look common and flattens exactly the
        # tokens that separate playbooks. The thesaurus is the right tool for
        # vocabulary mismatch; corpus statistics stay playbook-owned.
        self.idf = {t: math.log(n / c) for t, c in df.items()}
        self._default_idf = math.log(n) if n > 1 else 1.0

    def _derive_lane(self, playbook_path: Path) -> str | None:
        cited = re.findall(r"^- raw/(agentic|backend)/", playbook_path.read_text(encoding="utf-8"), flags=re.M)
        agentic, backend = cited.count("agentic"), cited.count("backend")
        if agentic > backend:
            return "agentic"
        if backend > agentic:
            return "backend"
        return None

    # --------------------------------------------------- vocabulary (v2)
    def _load_thesaurus(self) -> dict[str, list[str]]:
        """Reverse the thesaurus: synonym token -> canonical tokens to inject.

        thesaurus.json is authored canonical -> synonyms; routing needs the
        other direction. Every surface form (the canonical itself and each
        synonym) maps to the canonical token plus, for hyphenated concepts,
        its component words — "throttle" injects "rate-limiting", "rate",
        "limiting", meeting the corpus however a playbook spells it. A
        synonym claimed by several concepts (e.g. "fan-out") accumulates all
        of them and lets scoring arbitrate. Missing or malformed file -> no
        expansion, never an error.
        """
        try:
            raw = json.loads(self.thesaurus_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        rev: dict[str, list[str]] = {}
        for canon, syns in (raw.get("map") or {}).items():
            canon = canon.lower()
            inject = [t for t in dict.fromkeys([canon, *canon.split("-")])
                      if len(t) > 2]
            for form in dict.fromkeys([canon, *(s.lower() for s in syns)]):
                known = rev.setdefault(form, [])
                known.extend(t for t in inject if t not in known)
        return rev

    def _expand(self, toks: list[str]) -> list[str]:
        """Append canonical concept tokens for any synonym present in the brief.

        Purely additive and order-stable: original tokens keep their places,
        injected canonicals follow, nothing is ever added twice.
        """
        if not self._syn2canon:
            return toks
        out, seen = list(toks), set(toks)
        for t in toks:
            for canon in self._syn2canon.get(t, ()):
                if canon not in seen:
                    out.append(canon)
                    seen.add(canon)
        return out

    # ----------------------------------------------- semantic layer (v2)
    def _load_embeddings(self) -> dict[str, Any]:
        """Frozen corpus vectors written by build_embeddings.py.

        {} disables the semantic layer entirely (pure-lexical mode) when the
        file is absent or unreadable; validate_knowledge_router() reports
        coverage so staleness is visible instead of silent.
        """
        try:
            return json.loads((self.root / "embeddings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _load_operating_rules(self) -> str:
        """The always-on safe-execution frame (OPERATING_RULES.md, corpus root).

        Injected into EVERY non-empty packet right after the header — the one
        piece of the book that is deliberately NOT routed: a weak model gets
        the don't-break-things rules whether the brief asked for them or not
        (operator's directive, 2026-07-05). Missing file -> no section, and
        validate_knowledge_router() flags the absence as a corpus failure.
        """
        try:
            return _strip_fm((self.root / "OPERATING_RULES.md")
                             .read_text(encoding="utf-8")).strip()
        except OSError:
            return ""

    def _load_scenarios(self) -> dict[str, str]:
        """Per-playbook symptom lines (scenarios.json), reused by _retry_guide.

        The same file build_embeddings.py bakes into the corpus vectors; at
        serve time the abstain path shows these lines to the CALLING model so
        it can recognize which chapter its task actually is — a model that
        would never connect its task to a topic NAME recognizes it instantly
        in a symptom sentence. Missing or malformed file -> {}.
        """
        try:
            data = json.loads((self.root / "scenarios.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data.get("map") or {}

    def _retry_guide(self, ranked: list[tuple[float, str]]) -> dict[str, Any]:
        """Attached to every abstain, so a refusal TEACHES the second call.

        One-shot callers — weak models especially — treat a bare abstain as
        "no book here, proceed without it". The telemetry ledger caught that
        live on day one: an agent's summarized brief abstained with the
        correct chapter ranked #1 in closest-topics, and the agent went bare.
        This guide turns the refusal into instructions: the nearest chapters
        AS SYMPTOMS, their routing keywords, and the two retry moves that
        actually work.
        """
        closest = []
        for s, name in ranked[:3]:
            if s <= 0.0:
                break
            closest.append({
                "topic": name,
                "score": round(s, 4),
                "symptom": self._scenarios.get(name, ""),
                "keywords": name.replace("-", " "),
            })
        return {
            "closest_topics": closest,
            "how_to_retry": [
                "Call again passing the user's ORIGINAL message VERBATIM as user_message — "
                "summaries strip the concrete words that route.",
                "Or rewrite the brief in action words describing what the system DOES "
                "(click, drive, charge, queue, retry, upload), not abstract audit nouns.",
                "If a closest_topics symptom matches your task, include that topic's "
                "keywords in the brief and call again.",
            ],
        }

    def _embed_query(self, text: str) -> list[float] | None:
        """One live embed per route() call, against local ollama.

        Returns None — and the route stays pure lexical — when the semantic
        layer is disabled or the embed hop fails for ANY reason. The broad
        except is deliberate: this sits on the serving path of two live
        gateways, and no failure mode of a local model daemon is allowed to
        become a routing failure.
        """
        if not self._emb:
            return None
        try:
            payload = json.dumps({
                "model": self._emb.get("model", "nomic-embed-text"),
                "prompt": text[:2000],
            }).encode()
            req = urllib.request.Request(OLLAMA_EMBED_URL, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp).get("embedding")
        except Exception:
            return None

    @staticmethod
    def _blend_rerank(scored: list[tuple[float, str]],
                      sims: dict[str, float]) -> list[tuple[float, str]]:
        """Reorder (lexical_score, name) pairs by the SEM_ALPHA blend.

        One helper serves both channels so the blend has exactly one
        definition. Lexical is normalized against the pool max (scale-free);
        similarity is min-max normalized within the pool (spreads the pool's
        actual range). An entry with no embedding takes the pool minimum — a
        stale embeddings.json demotes an entry, never crashes a route. Ties
        break by name. Scores are returned UNCHANGED: they remain lexical
        truth, and every downstream floor keeps acting on lexical truth.
        """
        if not sims:
            return scored
        max_lex = max(s for s, _ in scored) or 1.0
        lo, hi = min(sims.values()), max(sims.values())
        spread = (hi - lo) or 1.0

        def blended(pair: tuple[float, str]) -> float:
            score, name = pair
            lex = score / max_lex
            sem = (sims.get(name, lo) - lo) / spread
            return SEM_ALPHA * lex + (1 - SEM_ALPHA) * sem

        return sorted(scored, key=lambda pair: (-blended(pair), pair[1]))

    # ------------------------------------------------------------- skills
    @staticmethod
    def _parse_skill(text: str) -> dict[str, str]:
        """Split a skill .md into (subtitle, h1, framing) for scoring.

        subtitle = the when-clause after the em-dash in the frontmatter
        ``source_title``; h1 = the ``# `` heading; framing = the first prose
        paragraph after the H1 (the "what this is for" paragraph).
        """
        fm, body = "", text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                fm, body = parts[1], parts[2]
        st = re.search(r"^source_title:\s*(.+)$", fm, flags=re.M)
        source_title = st.group(1).strip() if st else ""
        # em-dash separates "<Name> — <when-clause subtitle>"
        subtitle = (source_title.split("—", 1)[1].strip()
                    if "—" in source_title else source_title)
        h1_m = re.search(r"^#\s+(.+)$", body, flags=re.M)
        h1 = h1_m.group(1).strip() if h1_m else ""
        after_h1 = body[h1_m.end():] if h1_m else body
        framing = ""
        for block in re.split(r"\n\s*\n", after_h1):
            stripped = block.strip()
            if stripped and not stripped.startswith("#"):
                framing = stripped
                break
        return {"subtitle": subtitle, "h1": h1, "framing": framing}

    def _load_skills(self) -> None:
        """Load the method-skill channel. Silently no-op if skills/ is absent."""
        if not self.skills_dir.is_dir():
            return
        for path in sorted(self.skills_dir.glob("*.md")):
            meta = self._parse_skill(path.read_text(encoding="utf-8"))
            self._skill_meta[path.stem] = meta
            # Weight the subtitle (when-clause) heaviest, then the H1 topic name,
            # then the framing paragraph. Reuses the playbook IDF (self.idf) so a
            # brief token that is rare across playbooks stays informative here.
            self.skill_docs[path.stem] = (
                tokens(meta["subtitle"]) * SKILL_SUBTITLE_WEIGHT
                + tokens(meta["h1"]) * SKILL_H1_WEIGHT
                + tokens(meta["framing"])
            )

    def _score_skills(self, brief_toks: list[str],
                      qvec: list[float] | None = None) -> list[tuple[str, float]]:
        """Rank skills whose score clears SKILL_FLOOR *and* whose brief overlap
        spans >= SKILL_MIN_STEMS distinct word stems. Admission is pure
        lexical; when a query embedding is available, the admitted skills are
        re-ranked by the same blend the playbook channel uses, so among
        qualified skills the one that matches by MEANING can win. Returns up
        to SKILL_MAX_PICKS (name, score). Never touches playbook selection."""
        if not brief_toks:
            return []
        brief_set = set(brief_toks)
        scored: list[tuple[float, str]] = []
        for name, doc_toks in self.skill_docs.items():
            hits = brief_set & set(doc_toks)
            if len({_stem(t) for t in hits}) < SKILL_MIN_STEMS:
                continue
            s = self._score(brief_toks, doc_toks)
            if s >= SKILL_FLOOR:
                scored.append((round(s, 4), name))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        if qvec and len(scored) > 1:
            vecs = self._emb.get("skills", {})
            sims = {name: _cosine(qvec, vecs[name])
                    for _, name in scored if name in vecs}
            scored = self._blend_rerank(scored, sims)
        return [(name, s) for s, name in scored[:SKILL_MAX_PICKS]]

    # ------------------------------------------------------------ scoring
    def _score(self, brief_toks: list[str], doc_toks: list[str]) -> float:
        # Set-membership over the doc, by design. Making the x8 name boost
        # count as real term frequency (NAME_CAP swept 1..8) was tried on
        # 2026-07-04 and REVERTED by the bench: neutral at best (a cap <= 2 is
        # set membership by another name) and regressive on hit@2/AppSec above
        # that. Generalization comes from the thesaurus, not doc weighting.
        if not brief_toks:
            return 0.0
        doc_set = set(doc_toks)
        hit = sum(self.idf.get(t, 0.0) for t in brief_toks if t in doc_set)
        total = sum(self.idf.get(t, self._default_idf) for t in brief_toks)
        return hit / total if total else 0.0

    def _ranked(self, brief_toks: list[str]) -> list[tuple[float, str]]:
        return sorted(((self._score(brief_toks, dt), name) for name, dt in self.docs.items()),
                      key=lambda pair: (-pair[0], pair[1]))

    def _lex_affinity(self, brief_toks: list[str]) -> float:
        """Signed lane affinity in [-1, 1]: positive = agentic, negative = backend.

        Only lane-distinctive tokens vote; both-lane mush ("reads", "web") and
        rare one-off tokens do not (their df gap stays below LANE_LEX_GATE).
        """
        n_ag, n_be = self._lane_n["agentic"], self._lane_n["backend"]
        if not n_ag or not n_be:
            return 0.0
        signed = total = 0.0
        for t in brief_toks:
            weight = self.idf.get(t)
            if weight is None:
                continue
            p_ag = self._lane_df["agentic"].get(t, 0) / n_ag
            p_be = self._lane_df["backend"].get(t, 0) / n_be
            if abs(p_ag - p_be) < LANE_LEX_GATE:
                continue
            signed += weight * (p_ag - p_be)
            total += weight * max(p_ag, p_be)
        return signed / total if total else 0.0

    def _infer_brief_lane(self, brief_toks: list[str],
                          top5: list[tuple[float, str]]) -> tuple[str | None, str, dict[str, Any]]:
        lex = self._lex_affinity(brief_toks)
        mass = {"agentic": 0.0, "backend": 0.0}
        for s, name in top5:
            lane = self.lanes.get(name)
            if lane:
                mass[lane] += s
        evidence = {"lex_affinity": round(lex, 4),
                    "top5_lane_mass": {k: round(v, 4) for k, v in mass.items()}}
        if abs(lex) >= LANE_LEX_MARGIN:
            return ("agentic" if lex > 0 else "backend"), "lexical", evidence
        hi, lo = max(mass, key=mass.get), min(mass, key=mass.get)
        if mass[hi] > 0 and mass[hi] >= LANE_MASS_MARGIN * mass[lo]:
            return hi, "top5_mass", evidence
        return None, "undecided", evidence

    # ------------------------------------------------------------ routing
    def route(self, brief: str, k: int = 2, user_message: str = "") -> dict[str, Any]:
        k = max(1, min(int(k), 5))
        raw_toks = tokens(brief)
        if user_message:
            # v2 augment: fold the raw end-user text into the same scored bag,
            # so a brief that mis-summarizes the task can still route on what
            # the user actually said. Guarded so "" is byte-identical to
            # omitting the argument.
            raw_toks = raw_toks + tokens(user_message)
        # v2 expansion (brief side only; see _expand).
        brief_toks = self._expand(raw_toks)
        # ONE query embedding serves both channels below; None -> pure lexical.
        qvec = self._embed_query(f"{brief} {user_message}" if user_message else brief)
        ranked = self._ranked(brief_toks)
        top5 = ranked[:5]
        result: dict[str, Any] = {
            "picks": [],
            # Method-skill channel is orthogonal to the playbook channel: it is
            # a pure function of brief tokens and NEVER influences picks/abstain
            # below. Present on every return path (including abstain) so callers
            # get a stable shape; empty when no skill clears the gate.
            "skill_picks": self._score_skills(brief_toks, qvec),
            "top5": [(name, round(s, 4)) for s, name in top5],
            "lane_inference": {},
        }
        if not top5:
            result.update(abstain=True, reason="empty corpus")
            return result
        best = top5[0][0]
        brief_lane, method, evidence = self._infer_brief_lane(brief_toks, top5)
        lane_info: dict[str, Any] = {
            "brief_lane": brief_lane,
            "method": method,
            "top_pick_lane": self.lanes.get(top5[0][1]),
            "guard_triggered": False,
            **evidence,
        }
        result["lane_inference"] = lane_info

        # -- abstain gates (first-class outcome; see BENCH_REPORT_V2 priority 1)
        if best < HARD_FLOOR:
            result.update(abstain=True,
                          reason=f"no lexical match: best score {best:.3f} < {HARD_FLOOR}",
                          retry_guide=self._retry_guide(ranked))
            return result
        median5 = statistics.median([s for s, _ in top5])
        if best < SOFT_FLOOR and best < FLAT_RATIO * median5:
            # -- semantic rescue (v2.1): the weak-and-flat gate is lexical and
            # blind to meaning, so before refusing, ask the semantic channel
            # whether any qualified playbook is decisively close to the query
            # (>= RESCUE_SIM). Only THIS gate can be rescued — the hard floor
            # and the lane-conflict abstain below stay absolute.
            top_sim = 0.0
            if qvec:
                vecs = self._emb.get("playbooks", {})
                top_sim = max((_cosine(qvec, vecs[n])
                               for s, n in ranked if s >= MIN_SCORE and n in vecs),
                              default=0.0)
            if top_sim < RESCUE_SIM:
                result.update(abstain=True,
                              reason=(f"weak and flat: best {best:.3f} < {SOFT_FLOOR} and not clearly "
                                      f"above top-5 median {median5:.3f}"),
                              retry_guide=self._retry_guide(ranked))
                return result
            lane_info["semantic_rescued"] = round(top_sim, 4)

        # -- lane guard (BENCH_REPORT_V2 priority 3: orthogonal misroutes)
        pool = ranked
        top_lane = self.lanes.get(top5[0][1])
        if brief_lane and top_lane and top_lane != brief_lane:
            name_overlap = set(brief_toks) & set(tokens(top5[0][1].replace("-", " ")))
            lane_info["name_token_veto"] = sorted(name_overlap)
            corroborated = False
            if not name_overlap and qvec:
                # Second veto (v2.1, generalized v2.3): the guard exists to
                # catch cross-lane LEXICAL accidents, but when the semantic
                # channel independently places this same doc decisively close
                # to the query (>= RESCUE_SIM, the same corroboration floor
                # the rescue uses), two agreeing channels are the opposite of
                # an accident. Without this, an SSRF brief phrased in ops
                # words reads "agentic" to the lane lexicon and the guard
                # demotes the correct backend-lane answer both channels chose.
                # A genuine b27-class misroute stays demotable: its lexical
                # top is semantically DISTANT from the brief, which is exactly
                # what made it a misroute.
                vec = self._emb.get("playbooks", {}).get(top5[0][1])
                if vec and _cosine(qvec, vec) >= RESCUE_SIM:
                    corroborated = True
                    lane_info["sim_corroboration_veto"] = True
            if not name_overlap and not corroborated:
                same_lane = [(s, n) for s, n in ranked if self.lanes.get(n) == brief_lane]
                if same_lane and same_lane[0][0] >= MIN_SCORE:
                    pool = same_lane
                    lane_info["guard_triggered"] = True
                    lane_info["demoted_top_pick"] = top5[0][1]
                else:
                    result.update(abstain=True,
                                  reason=(f"lane conflict: top pick '{top5[0][1]}' is {top_lane} but "
                                          f"brief reads {brief_lane}, and no {brief_lane} playbook "
                                          f"scores above {MIN_SCORE}"),
                                  retry_guide=self._retry_guide(ranked))
                    return result

        # -- semantic re-rank (v2): meaning arbitrates order within the pool.
        # Runs strictly AFTER floors/abstain/lane-guard, and only over entries
        # already above MIN_SCORE: the picks loop below stops at the first
        # sub-floor entry it meets, so letting a lexically-rejected doc ride a
        # high similarity to the front of the pool could abstain a brief the
        # lexical core had already accepted. Restricting eligibility to the
        # qualified prefix (pool is score-descending, so it IS a prefix) keeps
        # the semantic layer a reorderer of accepted picks, nothing more.
        if qvec:
            eligible = [(s, n) for s, n in pool if s >= MIN_SCORE]
            if len(eligible) > 1:
                vecs = self._emb.get("playbooks", {})
                sims = {name: _cosine(qvec, vecs[name])
                        for _, name in eligible if name in vecs}
                if sims:
                    pool = self._blend_rerank(eligible, sims) + pool[len(eligible):]
                    lane_info["semantic_reranked"] = True

        picks: list[tuple[str, float]] = []
        for s, name in pool[:k]:
            if s < MIN_SCORE:
                break
            if picks and s < pool[0][0] * SECOND_PICK_RATIO:
                break
            picks.append((name, round(s, 4)))
        if not picks:
            result.update(abstain=True, reason=f"no pick above relevance floor {MIN_SCORE}",
                          retry_guide=self._retry_guide(ranked))
            return result
        result["picks"] = picks
        # v2: confidence is computed ONCE here, on the final picks and the full
        # expanded token bag (user_message included), and threaded through
        # resolve() -> assemble() so the packet header always agrees with it.
        result["confidence"] = self._confidence(picks, brief_toks)
        return result

    @staticmethod
    def _confidence(picks: list[tuple[str, float]], brief_toks: list[str]) -> float:
        """Deterministic routing confidence in [0,1]; surfaced, never gating.

        strength (the top pick's absolute score) blended 65/35 with separation
        (how clearly #1 beats #2), then scaled by a coverage factor. Coverage
        exists because the hit/total score inflates on thin briefs — a 2-token
        brief matching one token reads as 0.5 — so a brief under ~6 distinct
        tokens is capped in proportion to how much it actually gave the router
        to read.
        """
        if not picks:
            return 0.0
        top = picks[0][1]
        runner = picks[1][1] if len(picks) > 1 else 0.0
        strength = min(max(top, 0.0), 1.0)
        separation = (top - runner) / top if top else 0.0
        coverage = min(len(set(brief_toks)) / 6.0, 1.0)
        return round(min(1.0, (0.65 * strength + 0.35 * separation) * coverage), 3)

    # ----------------------------------------------------------- assembly
    def _raw_sources_for(self, picks: list[tuple[str, float]], limit: int = 3) -> list[str]:
        wanted: set[str] = set()
        for name, _ in picks:
            body = (self.playbooks_dir / f"{name}.md").read_text(encoding="utf-8")
            wanted |= set(re.findall(r"^- (raw/\S+\.md)", body, flags=re.M))
        out = []
        for rel in sorted(wanted):
            path = self.root / rel
            if not path.is_file():
                continue
            head = path.read_text(encoding="utf-8")[:600]
            tier = re.search(r"^tier: (\w)", head, flags=re.M)
            if tier and tier.group(1) == "A" and "REJECT" not in head:
                out.append(rel)
        return out[:limit]

    def _assemble_skills(self, skill_picks: list[tuple[str, float]], mode: str) -> str:
        """Render the ``## Method skills`` garnish section.

        micro: each skill's H1 + framing paragraph + a ``Full skill:`` pointer
        (never the procedural body — micro budgets can't afford it).
        compact/standard: the full skill body.
        """
        if not skill_picks:
            return ""
        blocks: list[str] = []
        for name, _ in skill_picks:
            body = _strip_fm((self.skills_dir / f"{name}.md").read_text(encoding="utf-8")).strip()
            if mode == "micro":
                meta = self._skill_meta.get(name, {})
                h1 = meta.get("h1", "")
                framing = meta.get("framing", "")
                block = "\n\n".join(p for p in (f"# {h1}" if h1 else "", framing) if p)
                block += f"\n\nFull skill: skills/{name}.md"
                blocks.append(block.strip())
            else:
                blocks.append(body)
        return "## Method skills\n\n" + "\n\n---\n\n".join(blocks)

    def _packet_header(self, picks: list[tuple[str, float]], brief: str,
                       confidence: float | None = None) -> str:
        """Framing header for every non-empty packet (module docstring, v2 §4).

        route() computes confidence on the full token bag and resolve()
        threads it through — recomputing here from the brief alone would
        disagree with result["confidence"] whenever user_message contributed
        tokens. Standalone assemble() callers may omit it, and the brief-only
        fallback is then the best information available.
        """
        if confidence is None:
            confidence = self._confidence(picks, self._expand(tokens(brief)))
        topics = ", ".join(f"{name} ({score:.4f})" for name, score in picks) or "(none)"
        n = len(picks)
        lines = [
            f"Routed topics ({n} pick{'s' if n != 1 else ''}, confidence {confidence:.2f}): {topics}",
            _FRAME_REFERENCE,
            _FRAME_CONTRACT,
        ]
        if _asks_for_tradeoff(brief):
            lines.append(_FRAME_TRADEOFF)
        return "\n".join(lines)

    def assemble(self, picks: list[tuple[str, float]], mode: str = "compact",
                 skill_picks: list[tuple[str, float]] | None = None,
                 brief: str = "", confidence: float | None = None) -> str:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        parts = []
        for name, _ in picks:
            micro = self.micro_dir / f"{name}.md"
            if micro.is_file():
                parts.append(_strip_fm(micro.read_text(encoding="utf-8")).strip())
            if mode in ("compact", "standard"):
                parts.append(_strip_fm((self.playbooks_dir / f"{name}.md").read_text(encoding="utf-8")).strip())
        if mode == "standard":
            for rel in self._raw_sources_for(picks):
                body = _strip_fm((self.root / rel).read_text(encoding="utf-8"))
                parts.append(f"[source excerpt: {rel}]\n" + body[:6000])
        # Method skills come LAST, clearly delimited, so playbook order is
        # untouched and the section is easy to strip if unwanted.
        skill_section = self._assemble_skills(skill_picks or [], mode)
        if skill_section:
            parts.append(skill_section)
        body = "\n\n---\n\n".join(parts)
        if not body:
            return body
        # v2: the framing header leads every non-empty packet; v2.2: the
        # operating rules ride immediately after it, in every mode — safety
        # framing is the one section that never depends on what was routed.
        lead = [self._packet_header(picks, brief, confidence)]
        if self._operating_rules:
            lead.append(self._operating_rules)
        return "\n\n---\n\n".join(lead + [body])

    def resolve(self, brief: str, mode: str = "compact", k: int = 2,
                user_message: str = "") -> dict[str, Any]:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        result = self.route(brief, k=k, user_message=user_message)
        result["packet"] = ("" if result.get("abstain")
                            else self.assemble(result["picks"], mode,
                                               skill_picks=result.get("skill_picks"),
                                               brief=brief,
                                               confidence=result.get("confidence")))
        return result


# ------------------------------------------------------------------ eval
def evaluate(root: str | Path | None = None, k: int = 2) -> dict[str, Any]:
    """Routing accuracy over bench/BRIEFS.jsonl (same math as v0 --eval)."""
    router = KnowledgeRouter(root)
    briefs = [json.loads(line) for line in router.briefs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    hit1 = hitk = with_exp = none_ok = none_tot = 0
    rows = []
    for b in briefs:
        expected = set(b.get("expected_playbooks", []))
        result = router.route(b["brief"], k=k)
        got = [name for name, _ in result["picks"]]
        if not expected:
            none_tot += 1
            if not got:
                none_ok += 1
            rows.append((b["id"], "no-playbook-expected", got, "OK" if not got else "FORCED"))
            continue
        with_exp += 1
        h1 = bool(got) and got[0] in expected
        hk = bool(expected & set(got))
        hit1 += h1
        hitk += hk
        if result.get("abstain"):
            verdict = "ABSTAINED"
        else:
            verdict = "hit1" if h1 else ("hitk" if hk else f"MISS top5={result['top5'][:3]}")
        rows.append((b["id"], sorted(expected), got, verdict))
    return {"rows": rows, "hit1": hit1, "hitk": hitk, "k": k, "with_expected": with_exp,
            "unrouted_ok": none_ok, "unrouted_total": none_tot}


def print_eval(root: str | Path | None = None, k: int = 2) -> None:
    report = evaluate(root, k=k)
    for row in report["rows"]:
        print(*row, sep=" | ")
    print(f"\nrouting accuracy over {report['with_expected']} briefs with expected playbooks: "
          f"hit@1 {report['hit1']}/{report['with_expected']}, "
          f"hit@{report['k']} {report['hitk']}/{report['with_expected']}; "
          f"no-packet briefs correctly unrouted: {report['unrouted_ok']}/{report['unrouted_total']}")


# ------------------------------------------------------------- MCP payloads
def resolve_knowledge_context(brief: str, mode: str = "compact", k: int = 2,
                              root: str | Path | None = None) -> dict[str, Any]:
    return KnowledgeRouter(root).resolve(brief, mode=mode, k=k)


def validate_knowledge_router(root: str | Path | None = None) -> dict[str, Any]:
    resolved = Path(root).expanduser().resolve() if root else default_root()
    checks: dict[str, Any] = {
        "corpus_root": str(resolved),
        "corpus_root_exists": resolved.is_dir(),
        "playbook_count": 0,
        "micro_count": 0,
        "skill_count": 0,
        "router_loads": False,
        "canned_brief_routes": False,
        "nonsense_brief_abstains": False,
        "canned_skill_routes": False,
    }
    try:
        router = KnowledgeRouter(resolved)
        checks["router_loads"] = True
        checks["playbook_count"] = len(router.docs)
        checks["micro_count"] = len(list(router.micro_dir.glob("*.md"))) if router.micro_dir.is_dir() else 0
        checks["skill_count"] = len(router.skill_docs)
        canned = router.resolve(
            "Design the retry policy for a payment service that calls a card processor: "
            "timeouts, retry counts, exponential backoff, and jitter at every hop.")
        checks["canned_brief_routes"] = bool(canned["picks"]) and bool(canned["packet"])
        checks["canned_picks"] = canned["picks"]
        nonsense = router.route("purple elephant sandwich orchestra")
        checks["nonsense_brief_abstains"] = bool(nonsense.get("abstain"))
        # Canned skill-routing check: an agent that browses the web and reads
        # untrusted email must pull the prompt-injection-defense method skill.
        skill_probe = router.route(
            "Our agent browses the web and reads emails. Design its defenses "
            "before we let it act on what it reads.")
        skill_names = [n for n, _ in skill_probe.get("skill_picks", [])]
        checks["canned_skill_picks"] = skill_probe.get("skill_picks", [])
        checks["canned_skill_routes"] = "prompt-injection-defense" in skill_names
        # v2.2: the always-on operating rules are a corpus REQUIREMENT — a
        # missing OPERATING_RULES.md silently strips the safety frame from
        # every packet, which is exactly the failure this check makes loud.
        checks["operating_rules_loaded"] = bool(router._operating_rules)
        # v2 semantic-layer health: coverage of the frozen embeddings vs the
        # live corpus. Entries added since the last build_embeddings.py run
        # route lexical-only and SILENTLY — this block makes that visible.
        # Coverage is a maintenance signal, not folded into all_pass:
        # pure-lexical is a supported mode, stale is a thing to go fix.
        checks["semantic_enabled"] = bool(router._emb)
        if router._emb:
            have_pb = router._emb.get("playbooks", {})
            have_sk = router._emb.get("skills", {})
            stale = ([n for n in router.docs if n not in have_pb]
                     + [n for n in router.skill_docs if n not in have_sk])
            checks["embedding_coverage"] = {
                "playbooks": f"{sum(n in have_pb for n in router.docs)}/{len(router.docs)}",
                "skills": f"{sum(n in have_sk for n in router.skill_docs)}/{len(router.skill_docs)}",
                "stale_entries": stale[:10],
            }
            checks["embeddings_current"] = not stale
    except (OSError, ValueError) as exc:
        checks["error"] = f"{type(exc).__name__}: {exc}"
    checks["all_pass"] = all((checks["corpus_root_exists"], checks["router_loads"],
                              checks["playbook_count"] > 0, checks["micro_count"] > 0,
                              checks["skill_count"] > 0, checks["canned_brief_routes"],
                              checks["nonsense_brief_abstains"], checks["canned_skill_routes"],
                              checks.get("operating_rules_loaded", False)))
    return checks
