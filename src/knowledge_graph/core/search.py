"""
Semantic Search - Embedding-based search using sentence-transformers.

Uses all-MiniLM-L6-v2 (384 dimensions) for local, offline semantic search.
Embeddings are stored as JSON in idea:embeddingJson triples.
"""

import json
import logging
from typing import Any

from .store import KnowledgeGraphStore, NAMESPACES
from .ideas import IdeasStore

logger = logging.getLogger(__name__)

IDEAS = NAMESPACES["ideas"]
IDEA = NAMESPACES["idea"]

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384


class SemanticSearch:
    """Embedding-based semantic search for ideas."""

    def __init__(self, store: KnowledgeGraphStore, ideas_store: IdeasStore):
        self._store = store
        self._ideas = ideas_store
        self._model = None

    def _get_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(EMBEDDING_MODEL)
                logger.info(f"Loaded embedding model: {EMBEDDING_MODEL}")
            except ImportError:
                raise RuntimeError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
        return self._model

    def _compute_embedding(self, text: str) -> list[float]:
        """Compute embedding for a text string."""
        model = self._get_model()
        # Truncate to 10,000 chars for efficiency
        text = text[:10000]
        embedding = model.encode(text)
        return embedding.tolist()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        import numpy as np
        a_arr = np.array(a, dtype=np.float32)
        b_arr = np.array(b, dtype=np.float32)
        dot = np.dot(a_arr, b_arr)
        norm_a = np.linalg.norm(a_arr)
        norm_b = np.linalg.norm(b_arr)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def search(
        self,
        query: str,
        top_k: int = 10,
        include_seeds: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Semantic search by meaning.

        Computes query embedding, retrieves stored embeddings, ranks by similarity.
        """
        query_embedding = self._compute_embedding(query)

        # Get all ideas with embeddings
        type_filter = ""
        if not include_seeds:
            type_filter = "FILTER NOT EXISTS { ?idea a <" + IDEA + "Seed> }"

        sparql = f"""
        SELECT ?idea ?title ?lifecycle ?embedding
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> ;
                  skos:prefLabel ?title ;
                  idea:embeddingJson ?embedding .
            OPTIONAL {{ ?idea idea:lifecycle ?lifecycle }}
            {type_filter}
        }}
        """

        results = self._store.query(sparql)

        scored = []
        for r in results:
            try:
                stored_embedding = json.loads(r["embedding"])
                score = self._cosine_similarity(query_embedding, stored_embedding)
                scored.append({
                    "id": r["idea"].replace(IDEAS, ""),
                    "title": r.get("title", ""),
                    "lifecycle": r.get("lifecycle", "seed"),
                    "score": round(score, 4),
                })
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def ensure_embeddings(self) -> dict[str, Any]:
        """Batch compute missing embeddings for all ideas."""
        # Find ideas without embeddings
        query = f"""
        SELECT ?idea ?title ?description ?content
        WHERE {{
            ?idea a skos:Concept ;
                  skos:inScheme <{IDEA}IdeaPool> ;
                  skos:prefLabel ?title .
            OPTIONAL {{ ?idea dcterms:description ?description }}
            OPTIONAL {{ ?idea idea:content ?content }}
            FILTER NOT EXISTS {{ ?idea idea:embeddingJson ?e }}
        }}
        """
        results = self._store.query(query)

        computed = 0
        failed = 0

        for r in results:
            idea_uri = r["idea"]
            # Build text for embedding: title + description + content
            parts = [r.get("title", "")]
            if r.get("description"):
                parts.append(r["description"])
            if r.get("content"):
                parts.append(r["content"])
            text = "\n\n".join(parts)

            try:
                embedding = self._compute_embedding(text)
                self._store.add_triple(
                    idea_uri,
                    f"{IDEA}embeddingJson",
                    json.dumps(embedding),
                    is_literal=True,
                )
                computed += 1
            except Exception as e:
                logger.error(f"Failed to compute embedding for {idea_uri}: {e}")
                failed += 1

        self._store.flush()
        return {
            "computed": computed,
            "failed": failed,
            "total_missing": len(results.bindings),
        }

    def explore_concept(self, concept: str, limit: int = 10) -> dict[str, Any]:
        """
        Hybrid concept exploration: keyword (SPARQL CONTAINS) + semantic.

        Returns both keyword matches and semantically similar ideas.
        """
        # Keyword search
        keyword_results = self._ideas.search_ideas(concept, limit=limit)

        # Semantic search (if model available)
        semantic_results = []
        try:
            semantic_results = self.search(concept, top_k=limit)
        except RuntimeError:
            logger.warning("Semantic search unavailable (sentence-transformers not installed)")

        # Merge and deduplicate
        seen = set()
        merged = []

        for r in keyword_results:
            if r["id"] not in seen:
                r["match_type"] = "keyword"
                merged.append(r)
                seen.add(r["id"])

        for r in semantic_results:
            if r["id"] not in seen:
                r["match_type"] = "semantic"
                merged.append(r)
                seen.add(r["id"])
            elif r["id"] in seen:
                # Update with score if already in results
                for m in merged:
                    if m["id"] == r["id"]:
                        m["semantic_score"] = r.get("score")
                        m["match_type"] = "both"
                        break

        return {
            "concept": concept,
            "keyword_count": len(keyword_results),
            "semantic_count": len(semantic_results),
            "results": merged[:limit],
        }
