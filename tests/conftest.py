"""
Pytest fixtures shared across the suite.

Stubs `sentence_transformers` when it isn't installed, since it pulls in
torch — a heavy dependency the unit/integration tests don't actually
need (retriever calls that would use it are mocked in the tests that
touch RAG). Real deployments still install the real package via
requirements.txt; this only affects local/CI test runs.
"""
from __future__ import annotations

import sys
import types

try:
    import sentence_transformers  # noqa: F401
except ImportError:
    _stub = types.ModuleType("sentence_transformers")

    class _StubSentenceTransformer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def encode(self, *args, **kwargs):
            return [[0.0] * 384]

    _stub.SentenceTransformer = _StubSentenceTransformer
    sys.modules["sentence_transformers"] = _stub

try:
    import tavily  # noqa: F401
except ImportError:
    _tavily_stub = types.ModuleType("tavily")

    class _StubTavilyClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, *args, **kwargs):
            return {"results": []}

    _tavily_stub.TavilyClient = _StubTavilyClient
    sys.modules["tavily"] = _tavily_stub
