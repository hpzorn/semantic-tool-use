"""Server-side MCP tool implementations.

These modules live outside the :mod:`tulla` package by design — they will be
deployed into the ontology-server process and therefore must NOT import
``tulla.*``.  All shared logic is re-implemented locally so the package is
substrate-neutral.
"""
