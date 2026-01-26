"""
Wikidata Cache - On-demand caching of Wikidata entities.

Fetches entity labels, descriptions, and basic properties from Wikidata
and caches them locally for fast access.

All cached data is stored in the named graph <wikidata:cache>.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any
from dataclasses import dataclass, field
import urllib.request
import urllib.error
import json

from .store import KnowledgeGraphStore, NAMESPACES, GRAPH_WIKIDATA

logger = logging.getLogger(__name__)

# Namespace shortcuts
RDF = NAMESPACES["rdf"]
RDFS = NAMESPACES["rdfs"]
XSD = NAMESPACES["xsd"]
SCHEMA = NAMESPACES["schema"]
WD = NAMESPACES["wd"]
IDEA = NAMESPACES["idea"]

# Wikidata API endpoints
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# Default cache TTL (7 days)
DEFAULT_TTL_DAYS = 7


@dataclass
class WikidataEntity:
    """A cached Wikidata entity."""
    qid: str  # e.g., "Q42"
    label: str | None = None
    description: str | None = None
    aliases: list[str] = field(default_factory=list)
    instance_of: list[str] = field(default_factory=list)  # list of QIDs
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def uri(self) -> str:
        """Get the Wikidata URI."""
        return f"{WD}{self.qid}"


class WikidataCache:
    """
    On-demand Wikidata entity cache.

    Provides:
    - Fetch entity data from Wikidata API
    - Local cache with TTL
    - Batch lookup
    - Search by label

    All cached data is stored in the named graph <http://ideasralph.org/graphs/wikidata>.
    """

    def __init__(self, store: KnowledgeGraphStore, ttl_days: int = DEFAULT_TTL_DAYS):
        """
        Initialize Wikidata cache.

        Args:
            store: The underlying knowledge graph store
            ttl_days: Cache TTL in days
        """
        self._store = store
        self._graph = GRAPH_WIKIDATA
        self._ttl = timedelta(days=ttl_days)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize the cache schema if not present."""
        logger.debug("Initializing Wikidata cache schema")

        # Define cachedAt property
        self._store.add_triple(
            f"{IDEA}cachedAt",
            f"{RDF}type",
            f"{RDF}Property",
            graph=self._graph
        )
        self._store.flush()

    def _is_cache_valid(self, qid: str) -> bool:
        """Check if cached entity is still valid (within TTL)."""
        query = f"""
        PREFIX idea: <{IDEA}>
        PREFIX xsd: <{XSD}>

        SELECT ?cachedAt
        WHERE {{
            GRAPH <{self._graph}> {{
                <{WD}{qid}> idea:cachedAt ?cachedAt .
            }}
        }}
        """

        results = self._store.query(query)
        if not results.bindings:
            return False

        cached_at_str = results.bindings[0].get("cachedAt")
        if not cached_at_str:
            return False

        try:
            cached_at = datetime.fromisoformat(cached_at_str.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) - cached_at < self._ttl
        except (ValueError, AttributeError):
            return False

    def _fetch_from_api(self, qid: str, lang: str = "en") -> WikidataEntity | None:
        """
        Fetch entity data from Wikidata API.

        Args:
            qid: Wikidata QID (e.g., "Q42")
            lang: Language code for labels/descriptions

        Returns:
            WikidataEntity or None if not found
        """
        params = {
            "action": "wbgetentities",
            "ids": qid,
            "format": "json",
            "languages": lang,
            "props": "labels|descriptions|aliases|claims"
        }

        url = f"{WIKIDATA_API}?" + "&".join(f"{k}={v}" for k, v in params.items())

        try:
            # Add User-Agent header as required by Wikidata
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "IdeasRalphKnowledgeGraph/1.0 (https://ideasralph.org)"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            if "entities" not in data or qid not in data["entities"]:
                logger.warning(f"Entity not found: {qid}")
                return None

            entity_data = data["entities"][qid]

            # Extract label
            label = None
            if "labels" in entity_data and lang in entity_data["labels"]:
                label = entity_data["labels"][lang]["value"]

            # Extract description
            description = None
            if "descriptions" in entity_data and lang in entity_data["descriptions"]:
                description = entity_data["descriptions"][lang]["value"]

            # Extract aliases
            aliases = []
            if "aliases" in entity_data and lang in entity_data["aliases"]:
                aliases = [a["value"] for a in entity_data["aliases"][lang]]

            # Extract instance_of (P31)
            instance_of = []
            if "claims" in entity_data and "P31" in entity_data["claims"]:
                for claim in entity_data["claims"]["P31"]:
                    if "mainsnak" in claim and "datavalue" in claim["mainsnak"]:
                        value = claim["mainsnak"]["datavalue"]["value"]
                        if "id" in value:
                            instance_of.append(value["id"])

            return WikidataEntity(
                qid=qid,
                label=label,
                description=description,
                aliases=aliases,
                instance_of=instance_of,
            )

        except urllib.error.URLError as e:
            logger.error(f"Failed to fetch Wikidata entity {qid}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Wikidata response for {qid}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching {qid}: {e}")
            return None

    def _cache_entity(self, entity: WikidataEntity) -> None:
        """Store entity in cache."""
        uri = entity.uri

        # Clear old cache for this entity
        self._clear_entity(entity.qid)

        # Store label
        if entity.label:
            self._store.add_triple(
                uri,
                f"{RDFS}label",
                entity.label,
                is_literal=True,
                lang="en",
                graph=self._graph
            )

        # Store description
        if entity.description:
            self._store.add_triple(
                uri,
                f"{SCHEMA}description",
                entity.description,
                is_literal=True,
                lang="en",
                graph=self._graph
            )

        # Store aliases using SKOS altLabel
        skos_ns = NAMESPACES.get("skos", "http://www.w3.org/2004/02/skos/core#")
        for alias in entity.aliases:
            self._store.add_triple(
                uri,
                f"{skos_ns}altLabel",
                alias,
                is_literal=True,
                lang="en",
                graph=self._graph
            )

        # Store instance_of
        for instance_qid in entity.instance_of:
            self._store.add_triple(
                uri,
                f"{WD}P31",  # instance of
                f"{WD}{instance_qid}",
                graph=self._graph
            )

        # Store cache timestamp
        self._store.add_triple(
            uri,
            f"{IDEA}cachedAt",
            entity.cached_at.isoformat(),
            datatype=f"{XSD}dateTime",
            graph=self._graph
        )

        self._store.flush()
        logger.debug(f"Cached entity: {entity.qid}")

    def _clear_entity(self, qid: str) -> None:
        """Clear cached data for an entity."""
        uri = f"{WD}{qid}"
        graph_node = self._store._node(self._graph)

        # Remove all triples about this entity in the cache graph
        quads = list(self._store.store.quads_for_pattern(
            self._store._node(uri), None, None, graph_node
        ))
        for quad in quads:
            self._store.store.remove(quad)

    def lookup(self, qid: str, force_refresh: bool = False) -> WikidataEntity | None:
        """
        Look up a Wikidata entity, using cache if available.

        Args:
            qid: Wikidata QID (e.g., "Q42")
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            WikidataEntity or None if not found
        """
        # Normalize QID
        if not qid.startswith("Q"):
            qid = f"Q{qid}"

        # Check cache
        if not force_refresh and self._is_cache_valid(qid):
            return self._get_cached_entity(qid)

        # Fetch from API
        entity = self._fetch_from_api(qid)
        if entity:
            self._cache_entity(entity)

        return entity

    def _get_cached_entity(self, qid: str) -> WikidataEntity | None:
        """Get entity from cache."""
        uri = f"{WD}{qid}"
        skos_ns = NAMESPACES.get("skos", "http://www.w3.org/2004/02/skos/core#")

        query = f"""
        PREFIX rdfs: <{RDFS}>
        PREFIX schema: <{SCHEMA}>
        PREFIX idea: <{IDEA}>

        SELECT ?label ?description ?cachedAt
        WHERE {{
            GRAPH <{self._graph}> {{
                OPTIONAL {{ <{uri}> rdfs:label ?label . FILTER(LANG(?label) = "en") }}
                OPTIONAL {{ <{uri}> schema:description ?description . FILTER(LANG(?description) = "en") }}
                OPTIONAL {{ <{uri}> idea:cachedAt ?cachedAt }}
            }}
        }}
        """

        results = self._store.query(query)
        if not results.bindings:
            return None

        row = results.bindings[0]

        # Get aliases
        aliases_query = f"""
        PREFIX skos: <{skos_ns}>
        SELECT ?alias
        WHERE {{
            GRAPH <{self._graph}> {{
                <{uri}> skos:altLabel ?alias .
            }}
        }}
        """
        aliases = [r["alias"] for r in self._store.query(aliases_query) if r.get("alias")]

        # Get instance_of
        instance_query = f"""
        SELECT ?instance
        WHERE {{
            GRAPH <{self._graph}> {{
                <{uri}> <{WD}P31> ?instanceUri .
                BIND(REPLACE(STR(?instanceUri), "{WD}", "") AS ?instance)
            }}
        }}
        """
        instance_of = [r["instance"] for r in self._store.query(instance_query) if r.get("instance")]

        # Parse cached_at
        cached_at = datetime.now(timezone.utc)
        if row.get("cachedAt"):
            try:
                cached_at = datetime.fromisoformat(row["cachedAt"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return WikidataEntity(
            qid=qid,
            label=row.get("label"),
            description=row.get("description"),
            aliases=aliases,
            instance_of=instance_of,
            cached_at=cached_at,
        )

    def batch_lookup(self, qids: list[str], force_refresh: bool = False) -> dict[str, WikidataEntity | None]:
        """
        Look up multiple entities.

        Args:
            qids: List of Wikidata QIDs
            force_refresh: If True, bypass cache

        Returns:
            Dict mapping QID to WikidataEntity (or None if not found)
        """
        results = {}
        for qid in qids:
            results[qid] = self.lookup(qid, force_refresh)
        return results

    def search(self, term: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Search for entities in cache by label.

        Args:
            term: Search term
            limit: Maximum results

        Returns:
            List of matching entities
        """
        term = term.lower().replace('"', '\\"')

        query = f"""
        PREFIX rdfs: <{RDFS}>
        PREFIX schema: <{SCHEMA}>

        SELECT DISTINCT ?entity ?label ?description
        WHERE {{
            GRAPH <{self._graph}> {{
                ?entity rdfs:label ?label .
                FILTER(CONTAINS(LCASE(?label), "{term}"))
                OPTIONAL {{ ?entity schema:description ?description }}
            }}
        }}
        LIMIT {limit}
        """

        results = self._store.query(query)
        return [
            {
                "qid": r["entity"].replace(WD, "") if r.get("entity") else None,
                "label": r.get("label"),
                "description": r.get("description"),
            }
            for r in results
        ]

    def get_cached_entities(self) -> list[str]:
        """Get list of all cached QIDs."""
        query = f"""
        PREFIX idea: <{IDEA}>

        SELECT DISTINCT ?entity
        WHERE {{
            GRAPH <{self._graph}> {{
                ?entity idea:cachedAt ?cachedAt .
            }}
        }}
        """

        results = self._store.query(query)
        return [
            r["entity"].replace(WD, "")
            for r in results
            if r.get("entity") and r["entity"].startswith(WD)
        ]

    def count_cached(self) -> int:
        """Count cached entities."""
        return len(self.get_cached_entities())

    def get_stale_entities(self) -> list[str]:
        """Get entities that need refreshing (past TTL)."""
        cutoff = datetime.now(timezone.utc) - self._ttl

        query = f"""
        PREFIX idea: <{IDEA}>
        PREFIX xsd: <{XSD}>

        SELECT DISTINCT ?entity
        WHERE {{
            GRAPH <{self._graph}> {{
                ?entity idea:cachedAt ?cachedAt .
                FILTER(?cachedAt < "{cutoff.isoformat()}"^^xsd:dateTime)
            }}
        }}
        """

        results = self._store.query(query)
        return [
            r["entity"].replace(WD, "")
            for r in results
            if r.get("entity") and r["entity"].startswith(WD)
        ]

    def refresh_stale(self) -> int:
        """Refresh all stale entities. Returns count of refreshed entities."""
        stale = self.get_stale_entities()
        count = 0
        for qid in stale:
            if self.lookup(qid, force_refresh=True):
                count += 1
        return count

    def clear_cache(self) -> int:
        """Clear all cached entities."""
        count = self._store.clear_graph(self._graph)
        self._init_schema()
        logger.info(f"Cleared Wikidata cache ({count} triples)")
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        cached = self.get_cached_entities()
        stale = self.get_stale_entities()

        return {
            "total_cached": len(cached),
            "stale_count": len(stale),
            "ttl_days": self._ttl.days,
            "graph_triples": self._store.count_triples(self._graph),
        }
