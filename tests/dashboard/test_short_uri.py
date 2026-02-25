"""Unit tests for the short_uri Jinja2 filter."""

from __future__ import annotations

import pytest

from ontology_server.dashboard import short_uri


class TestShortUri:
    """Tests for the short_uri() filter function."""

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("http://tulla.dev/phase#D1Output", "phase:D1Output"),
            ("http://tulla.dev/prd#req-74-2-2", "prd:req-74-2-2"),
            ("http://tulla.dev/trace#run-001", "trace:run-001"),
            ("http://www.w3.org/2004/02/skos/core#Concept", "skos:Concept"),
        ],
    )
    def test_known_prefix_shortened(self, uri: str, expected: str) -> None:
        """URIs with known namespace prefixes are abbreviated."""
        assert short_uri(uri) == expected

    def test_unknown_prefix_unchanged(self) -> None:
        """URIs with no matching prefix are returned verbatim."""
        uri = "http://example.org/unknown#Thing"
        assert short_uri(uri) == uri

    def test_bare_namespace_no_local(self) -> None:
        """A URI equal to just the namespace prefix produces 'prefix:' with empty local."""
        assert short_uri("http://tulla.dev/phase#") == "phase:"

    def test_empty_string(self) -> None:
        """An empty string returns an empty string."""
        assert short_uri("") == ""

    def test_first_match_wins(self) -> None:
        """The first matching prefix in the list is used."""
        # All four prefixes are distinct so this just verifies iteration order
        uri = "http://tulla.dev/phase#SomePhase"
        result = short_uri(uri)
        assert result.startswith("phase:")
