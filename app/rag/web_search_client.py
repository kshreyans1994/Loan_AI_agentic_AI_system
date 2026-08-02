"""
Web search client.

Behind an interface for the same reason OCR/VLM/credit-bureau are: swap
providers without touching calling code. Tavily is the default
implementation since it's already part of your travel-planner stack —
a search API purpose-built for LLM agents (concise, citation-friendly
results) rather than raw SERP scraping.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.config import get_settings
from app.core.schemas import WebSearchResult


class WebSearchClient(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 3) -> list[WebSearchResult]:
        ...


class TavilySearchClient(WebSearchClient):
    def __init__(self) -> None:
        from tavily import TavilyClient  # local import: optional dependency

        settings = get_settings()
        self.client = TavilyClient(api_key=settings.tavily_api_key)

    def search(self, query: str, max_results: int = 3) -> list[WebSearchResult]:
        response = self.client.search(query=query, max_results=max_results)
        return [
            WebSearchResult(
                title=r.get("title", ""),
                snippet=r.get("content", ""),
                url=r.get("url", ""),
            )
            for r in response.get("results", [])
        ]


def get_web_search_client() -> WebSearchClient:
    return TavilySearchClient()
