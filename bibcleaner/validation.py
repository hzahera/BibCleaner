from __future__ import annotations

from typing import Any

import bibtexparser

from .bib_rules import BIB_ENTRY_RULES, normalize_entry_type


def _entry_fields(entry: bibtexparser.model.Entry) -> dict[str, str]:
    fields: dict[str, str] = {}
    for field in entry.fields:
        fields[field.key.strip().lower()] = str(field.value or "").strip()
    return fields


def validate_bibliography_content(content: str | bytes) -> list[dict[str, Any]]:
    if isinstance(content, bytes):
        try:
            bibtex_str = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Input file must be UTF-8 encoded") from exc
    else:
        bibtex_str = content

    if not bibtex_str.strip():
        raise ValueError("Input bibliography is empty")

    try:
        library = bibtexparser.parse_string(bibtex_str)
    except Exception as exc:
        raise ValueError(f"Failed to parse BibTeX input: {exc}") from exc

    entries = [b for b in library.blocks if isinstance(b, bibtexparser.model.Entry)]

    results: list[dict[str, Any]] = []
    for entry in entries:
        entry_type = normalize_entry_type(entry.entry_type)
        entry_rules = BIB_ENTRY_RULES.get(entry_type)

        missing_required: list[str] = []
        missing_optional: list[str] = []
        warnings: list[str] = []

        if entry_rules is None:
            warnings.append(f"unknown entry type: {entry_type}")
        else:
            fields = _entry_fields(entry)
            missing_required = [
                field_name
                for field_name in entry_rules.required_fields
                if not fields.get(field_name)
            ]
            missing_optional = [
                field_name
                for field_name in entry_rules.optional_fields
                if not fields.get(field_name)
            ]
            warnings.extend(missing_optional)

        results.append(
            {
                "entry_id": entry.key,
                "errors": missing_required,
                "warnings": warnings,
            }
        )

    return results
