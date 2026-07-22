from __future__ import annotations

import json
import math
import os
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .index_store import PackIndexRecord
from .normalizer import tokenize
from .schemas import DesignContextRequest
from .visual_features import visual_similarity, visual_target_from_request
from .visual_index import load_visual_index


RETRIEVAL_STOP = {
    "a",
    "an",
    "and",
    "app",
    "build",
    "create",
    "design",
    "for",
    "from",
    "homepage",
    "interface",
    "layout",
    "page",
    "screen",
    "site",
    "the",
    "this",
    "to",
    "tool",
    "unknown",
    "website",
    "with",
}


@dataclass(frozen=True)
class HybridResult:
    pack_id: str
    fused_score: float
    normalized_score: float
    channel_scores: dict[str, float]
    channel_ranks: dict[str, int]


def document_text(record: PackIndexRecord) -> str:
    manifest = record.manifest
    return (
        " ".join(
            [
                manifest.pack_id.replace("_", " "),
                manifest.family.replace(".", " "),
                *manifest.origin_example_ids,
                *manifest.surfaces,
                *manifest.tones,
                *manifest.motif_tags,
                *manifest.supports_tasks,
            ]
        )
        .replace("_", " ")
        .replace("-", " ")
    )


def _query_text(request: DesignContextRequest) -> str:
    return " ".join(
        [
            request.task,
            *request.tone,
            *request.constraints,
        ]
    )


def _terms(text: str) -> list[str]:
    return sorted(
        term
        for term in tokenize([text])
        if term not in RETRIEVAL_STOP and len(term) > 2
    )


def _char_ngrams(text: str, size: int = 3) -> set[str]:
    normalized = " ".join(_terms(text))
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {
        normalized[index : index + size] for index in range(len(normalized) - size + 1)
    }


def _dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return (2.0 * len(left.intersection(right))) / (len(left) + len(right))


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class HybridRetriever:
    """Deterministic multi-channel candidate retrieval.

    The rules-based router remains the safety channel. BM25 and character
    retrieval are dependency-free. Frozen dense vectors are optional and can
    never make routing unavailable: missing files, endpoints, or model calls
    simply remove the dense channel from rank fusion.
    """

    def __init__(self, repo_root: Path, records: list[PackIndexRecord]) -> None:
        self.repo_root = repo_root
        self.records = list(records)
        self.documents = {
            record.pack_id: document_text(record) for record in self.records
        }
        self.term_counts = {
            pack_id: Counter(_terms(text)) for pack_id, text in self.documents.items()
        }
        self.document_lengths = {
            pack_id: sum(counts.values())
            for pack_id, counts in self.term_counts.items()
        }
        self.average_length = (
            sum(self.document_lengths.values()) / len(self.document_lengths)
            if self.document_lengths
            else 1.0
        )
        document_frequency: Counter[str] = Counter()
        for counts in self.term_counts.values():
            document_frequency.update(counts)
        total = max(1, len(self.term_counts))
        self.idf = {
            term: math.log(1.0 + ((total - frequency + 0.5) / (frequency + 0.5)))
            for term, frequency in document_frequency.items()
        }
        self.document_ngrams = {
            pack_id: _char_ngrams(text) for pack_id, text in self.documents.items()
        }
        self.visual_index = load_visual_index(repo_root)
        self.visual_documents = {
            pack_id: " ".join(row.get("visual_terms", []))
            for pack_id, row in self.visual_index.get("anchors", {}).items()
            if isinstance(row, dict)
        }
        self.visual_term_counts = {
            pack_id: Counter(_terms(text))
            for pack_id, text in self.visual_documents.items()
        }
        self.pixel_profiles = {
            pack_id: row.get("pixel_profile", {})
            for pack_id, row in self.visual_index.get("anchors", {}).items()
            if isinstance(row, dict) and row.get("pixel_profile", {}).get("available")
        }
        self.embedding_data = self._load_embeddings()

    def _load_embeddings(self) -> dict[str, Any]:
        path = self.repo_root / ".design_router" / "design_embeddings.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        anchors = data.get("anchors")
        return data if isinstance(anchors, dict) else {}

    def _query_embedding(self, text: str) -> list[float] | None:
        if not self.embedding_data or os.getenv("DESIGN_ROUTER_LIVE_EMBEDDINGS") != "1":
            return None
        endpoint = os.getenv(
            "DESIGN_ROUTER_EMBED_URL",
            "http://localhost:11434/api/embed",
        )
        model = str(self.embedding_data.get("model") or "nomic-embed-text")
        payload = json.dumps({"model": model, "input": text[:4000]}).encode()
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.load(response)
        except Exception:
            return None
        vector = data.get("embedding")
        if not isinstance(vector, list):
            embeddings = data.get("embeddings")
            vector = (
                embeddings[0] if isinstance(embeddings, list) and embeddings else None
            )
        return vector if isinstance(vector, list) else None

    def _bm25_scores(
        self, query_terms: list[str], allowed: set[str]
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        k1 = 1.5
        b = 0.75
        for pack_id in allowed:
            counts = self.term_counts.get(pack_id, Counter())
            length = self.document_lengths.get(pack_id, 0)
            score = 0.0
            for term in query_terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + k1 * (
                    1.0 - b + b * (length / max(1.0, self.average_length))
                )
                score += self.idf.get(term, 0.0) * (
                    frequency * (k1 + 1.0) / denominator
                )
            scores[pack_id] = score
        return scores

    def _character_scores(self, query: str, allowed: set[str]) -> dict[str, float]:
        query_ngrams = _char_ngrams(query)
        return {
            pack_id: _dice(query_ngrams, self.document_ngrams.get(pack_id, set()))
            for pack_id in allowed
        }

    def _dense_scores(self, query: str, allowed: set[str]) -> dict[str, float]:
        query_vector = self._query_embedding(query)
        if query_vector is None:
            return {}
        anchors = self.embedding_data.get("anchors", {})
        return {
            pack_id: _cosine(query_vector, anchors[pack_id])
            for pack_id in allowed
            if isinstance(anchors.get(pack_id), list)
        }

    def _visual_scores(
        self, query_terms: list[str], allowed: set[str]
    ) -> dict[str, float]:
        if not self.visual_term_counts:
            return {}
        query_counts = Counter(query_terms)
        return {
            pack_id: sum(
                min(count, self.visual_term_counts.get(pack_id, Counter()).get(term, 0))
                for term, count in query_counts.items()
            )
            for pack_id in allowed
        }

    def _pixel_scores(
        self, request: DesignContextRequest, allowed: set[str]
    ) -> dict[str, float]:
        target = visual_target_from_request(request, repo_root=self.repo_root)
        if not target.get("active"):
            return {}
        return {
            pack_id: visual_similarity(target, self.pixel_profiles[pack_id])
            for pack_id in allowed
            if pack_id in self.pixel_profiles
        }

    @staticmethod
    def _rank(scores: dict[str, float]) -> list[str]:
        return [
            pack_id
            for pack_id, score in sorted(
                scores.items(), key=lambda item: (-item[1], item[0])
            )
            if score > 0.0
        ]

    def rank(
        self,
        request: DesignContextRequest,
        records: list[PackIndexRecord],
        *,
        rules_rank: list[str],
        query_expansions: list[str] | None = None,
        include_pixel: bool = False,
    ) -> list[HybridResult]:
        allowed = {record.pack_id for record in records}
        query = " ".join([_query_text(request), *(query_expansions or [])])
        query_terms = _terms(query)
        channel_scores = {
            "rules": {
                pack_id: float(len(rules_rank) - rank)
                for rank, pack_id in enumerate(rules_rank)
                if pack_id in allowed
            },
            "bm25": self._bm25_scores(query_terms, allowed),
            "character": self._character_scores(query, allowed),
            "visual": self._visual_scores(query_terms, allowed),
            "pixel": self._pixel_scores(request, allowed) if include_pixel else {},
            "dense": self._dense_scores(query, allowed),
        }
        pixel_coverage = (
            len(set(self.pixel_profiles).intersection(allowed)) / len(allowed)
            if allowed
            else 0.0
        )
        channel_weights = {
            "rules": 1.4,
            "bm25": 1.0,
            "character": 0.65,
            "visual": 0.55,
            "pixel": 0.75 * max(0.2, min(1.0, pixel_coverage / 0.75)),
            "dense": 1.2,
        }
        rankings = {
            channel: self._rank(scores)
            for channel, scores in channel_scores.items()
            if scores
        }
        fused: dict[str, float] = {pack_id: 0.0 for pack_id in allowed}
        ranks_by_pack: dict[str, dict[str, int]] = {pack_id: {} for pack_id in allowed}
        for channel, ranking in rankings.items():
            weight = channel_weights[channel]
            for rank, pack_id in enumerate(ranking, start=1):
                fused[pack_id] += weight / (20.0 + rank)
                ranks_by_pack[pack_id][channel] = rank
        maximum = max(fused.values(), default=0.0) or 1.0
        results = [
            HybridResult(
                pack_id=pack_id,
                fused_score=score,
                normalized_score=score / maximum,
                channel_scores={
                    channel: round(scores.get(pack_id, 0.0), 6)
                    for channel, scores in channel_scores.items()
                    if scores
                },
                channel_ranks=ranks_by_pack[pack_id],
            )
            for pack_id, score in fused.items()
        ]
        return sorted(results, key=lambda item: (-item.fused_score, item.pack_id))

    def health(self) -> dict[str, Any]:
        anchors = self.embedding_data.get("anchors", {}) if self.embedding_data else {}
        covered = sum(1 for record in self.records if record.pack_id in anchors)
        visual_covered = sum(
            1 for record in self.records if record.pack_id in self.visual_documents
        )
        return {
            "channels": ["rules", "bm25", "character"]
            + (["visual"] if self.visual_documents else [])
            + (["pixel"] if self.pixel_profiles else [])
            + (["dense"] if self.embedding_data else []),
            "visual_index_present": bool(self.visual_index),
            "visual_index_version": self.visual_index.get("version")
            if self.visual_index
            else None,
            "visual_coverage": {
                "covered": visual_covered,
                "total": len(self.records),
            },
            "pixel_coverage": {
                "covered": len(self.pixel_profiles),
                "total": len(self.records),
            },
            "dense_index_present": bool(self.embedding_data),
            "dense_model": self.embedding_data.get("model")
            if self.embedding_data
            else None,
            "dense_coverage": {
                "covered": covered,
                "total": len(self.records),
            },
            "live_dense_enabled": os.getenv("DESIGN_ROUTER_LIVE_EMBEDDINGS") == "1",
        }
