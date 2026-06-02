from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ProviderQuery:
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[str] = None
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None


@dataclass
class ProviderResult:
    # Structured published-venue data (entry_type, journal/booktitle, year, ...)
    published_data: Optional[Dict] = None
    # Authors recovered for a still-unpublished preprint
    preprint_authors: List[str] = field(default_factory=list)
    # Canonical author list (e.g. exactly as submitted to arXiv)
    canonical_authors: List[str] = field(default_factory=list)
    primaryclass: Optional[str] = None
    year: Optional[str] = None
    # A DOI discovered for the work (used to drive an exact DOI lookup)
    doi: Optional[str] = None
    # Author-declared venue string from arXiv (<arxiv:journal_ref>)
    journal_ref: Optional[str] = None
    # True if the provider confidently identified the paper at all,
    # whether or not it turned out to be published.
    matched: bool = False


class Provider(ABC):
    name = "provider"

    @abstractmethod
    def lookup(self, query: ProviderQuery) -> ProviderResult:
        """Resolve metadata for the given query."""
