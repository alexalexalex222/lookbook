from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from .hybrid_retrieval import document_text
from .index_store import build_repository_index


class EmbeddingIndexError(RuntimeError):
    pass


def default_embedding_index_path(repo_root: Path) -> Path:
    return repo_root / ".design_router" / "design_embeddings.json"


def _post_json(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except Exception as exc:
        raise EmbeddingIndexError(
            f"Embedding endpoint unavailable at {endpoint}: {exc}"
        ) from exc
    if not isinstance(result, dict):
        raise EmbeddingIndexError("Embedding endpoint returned a non-object response.")
    return result


def _extract_embeddings(payload: dict[str, Any]) -> list[list[float]]:
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and all(isinstance(row, list) for row in embeddings):
        return embeddings
    embedding = payload.get("embedding")
    if isinstance(embedding, list):
        return [embedding]
    raise EmbeddingIndexError("Embedding endpoint response did not include embeddings.")


def build_embedding_index(
    repo_root: Path | str,
    *,
    model: str = "nomic-embed-text",
    endpoint: str | None = None,
    batch_size: int = 16,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    if batch_size < 1 or batch_size > 128:
        raise ValueError("batch_size must be between 1 and 128")
    root = Path(repo_root).expanduser().resolve()
    resolved_endpoint = endpoint or os.getenv(
        "DESIGN_ROUTER_EMBED_URL",
        "http://localhost:11434/api/embed",
    )
    index = build_repository_index(root)
    documents = {
        record.manifest.pack_id: document_text(record)
        for record in index.anchors
    }
    pack_ids = sorted(documents)
    anchors: dict[str, list[float]] = {}
    dimensions: set[int] = set()
    for offset in range(0, len(pack_ids), batch_size):
        batch_ids = pack_ids[offset : offset + batch_size]
        response = _post_json(
            resolved_endpoint,
            {
                "model": model,
                "input": [documents[pack_id] for pack_id in batch_ids],
            },
        )
        vectors = _extract_embeddings(response)
        if len(vectors) != len(batch_ids):
            raise EmbeddingIndexError(
                f"Embedding endpoint returned {len(vectors)} vectors for {len(batch_ids)} inputs."
            )
        for pack_id, vector in zip(batch_ids, vectors):
            if not vector or not all(isinstance(value, (int, float)) for value in vector):
                raise EmbeddingIndexError(f"Invalid embedding vector for {pack_id}.")
            anchors[pack_id] = [float(value) for value in vector]
            dimensions.add(len(vector))
    if len(dimensions) != 1:
        raise EmbeddingIndexError(
            f"Embedding dimensions are inconsistent: {sorted(dimensions)}"
        )
    fingerprint_source = json.dumps(
        {
            "model": model,
            "documents": documents,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    payload = {
        "version": "1.0",
        "model": model,
        "endpoint": resolved_endpoint,
        "dimensions": next(iter(dimensions), 0),
        "anchor_count": len(anchors),
        "document_fingerprint": hashlib.sha256(fingerprint_source).hexdigest(),
        "anchors": anchors,
    }
    path = (
        Path(output_path).expanduser().resolve()
        if output_path
        else default_embedding_index_path(root)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {
        "path": str(path),
        "model": model,
        "endpoint": resolved_endpoint,
        "anchor_count": len(anchors),
        "dimensions": payload["dimensions"],
        "document_fingerprint": payload["document_fingerprint"],
    }
