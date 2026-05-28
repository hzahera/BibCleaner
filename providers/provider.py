from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ProviderQuery:
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[str] = None
    arxiv_id: Optional[str] = None


@dataclass
class ProviderResult:
    published_data: Optional[Dict] = None
    preprint_authors: List[str] = field(default_factory=list)
    canonical_authors: List[str] = field(default_factory=list)
    primaryclass: Optional[str] = None


class Provider(ABC):
    name = "provider"

    @abstractmethod
    def lookup(self, query: ProviderQuery) -> ProviderResult:
        """Resolve metadata for the given query."""
