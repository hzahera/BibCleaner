import bibcleaner.dblp as dblp

from .provider import Provider, ProviderQuery, ProviderResult


class DblpProvider(Provider):
    name = "dblp"

    def lookup(self, query: ProviderQuery) -> ProviderResult:
        result = dblp.lookup(query.title, query.authors, query.year)
        published = result.get("published")
        preprint = result.get("preprint")

        published_data = dblp.normalize(published) if published else None
        preprint_authors = []
        if preprint:
            preprint_authors = dblp.normalize(preprint).get("authors", [])

        return ProviderResult(
            published_data=published_data,
            preprint_authors=preprint_authors,
        )
