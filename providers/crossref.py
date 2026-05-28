import bibcleaner.crossref as crossref

from .provider import Provider, ProviderQuery, ProviderResult


class CrossrefProvider(Provider):
    name = "crossref"

    def lookup(self, query: ProviderQuery) -> ProviderResult:
        item = crossref.best_match(query.title, query.authors, query.year)
        if not item:
            return ProviderResult()

        data = crossref.normalize(item)
        return ProviderResult(published_data=data)
