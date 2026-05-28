from bibcleaner.arxiv_api import fetch as fetch_arxiv

from .provider import Provider, ProviderQuery, ProviderResult


class ArxivProvider(Provider):
    name = "arxiv"

    def lookup(self, query: ProviderQuery) -> ProviderResult:
        if not query.arxiv_id:
            return ProviderResult()

        meta = fetch_arxiv(query.arxiv_id)
        if not meta:
            return ProviderResult()

        return ProviderResult(
            canonical_authors=meta.get("authors") or [],
            primaryclass=meta.get("primaryclass"),
        )
