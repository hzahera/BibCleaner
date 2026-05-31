from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class EntryTypeRule:
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]


def normalize_entry_type(entry_type: str | None) -> str:
    return (entry_type or "").strip().lower().lstrip("@")


BIB_ENTRY_RULES: Final[dict[str, EntryTypeRule]] = {
    "article": EntryTypeRule(
        required_fields=("author", "title", "journal", "year"),
        optional_fields=("volume", "number", "pages", "month", "doi", "url"),
    ),
    "book": EntryTypeRule(
        required_fields=("author", "title", "publisher", "year"),
        optional_fields=("volume", "series", "address", "edition", "doi", "isbn"),
    ),
    "inproceedings": EntryTypeRule(
        required_fields=("author", "title", "booktitle", "year"),
        optional_fields=("pages", "address", "publisher", "doi"),
    ),
    "conference": EntryTypeRule(
        required_fields=("author", "title", "booktitle", "year"),
        optional_fields=("pages", "address", "publisher"),
    ),
    "phdthesis": EntryTypeRule(
        required_fields=("author", "title", "school", "year"),
        optional_fields=("address", "month", "type", "doi"),
    ),
    "mastersthesis": EntryTypeRule(
        required_fields=("author", "title", "school", "year"),
        optional_fields=("address", "month", "type"),
    ),
    "techreport": EntryTypeRule(
        required_fields=("author", "title", "institution", "year"),
        optional_fields=("type", "number", "address", "month"),
    ),
    "misc": EntryTypeRule(
        required_fields=("author", "title"),
        optional_fields=("year", "url", "note", "howpublished"),
    ),
    "unpublished": EntryTypeRule(
        required_fields=("author", "title", "note"),
        optional_fields=("year", "month"),
    ),
    "proceedings": EntryTypeRule(
        required_fields=("title", "year"),
        optional_fields=("editor", "publisher", "address", "volume"),
    ),
    "manual": EntryTypeRule(
        required_fields=("title",),
        optional_fields=("author", "organization", "year", "edition"),
    ),
    "incollection": EntryTypeRule(
        required_fields=("author", "title", "booktitle", "publisher", "year"),
        optional_fields=("editor", "chapter", "pages", "address"),
    ),
}
