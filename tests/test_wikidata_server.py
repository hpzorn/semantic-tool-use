"""Tests for the extracted standalone Wikidata MCP server."""

import pytest

from knowledge_graph import KnowledgeGraphStore
from wikidata_server import create_wikidata_server


@pytest.fixture
def wikiserver():
    return create_wikidata_server(KnowledgeGraphStore())


def _fn(srv, name):
    return srv._tool_manager.get_tool(name).fn


def test_exposes_exactly_four_tools(wikiserver):
    names = set(wikiserver._tool_manager._tools)
    assert names == {"lookup", "query", "search_cache", "stats"}


def test_stats_returns_dict(wikiserver):
    assert isinstance(_fn(wikiserver, "stats")(), dict)


def test_search_cache_empty(wikiserver):
    # local cache, no network
    assert isinstance(_fn(wikiserver, "search_cache")("nothing", limit=5), list)


def test_server_name(wikiserver):
    assert wikiserver.name == "wikidata-server"
