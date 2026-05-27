"""Unit tests for bibcleaner enricher helpers."""

import pytest
from bibcleaner.enricher import extract_arxiv_id, _is_truncated, _format_authors


def test_extract_arxiv_id_from_eprint():
    assert extract_arxiv_id({"eprint": "2410.03834"}) == "2410.03834"


def test_extract_arxiv_id_strips_prefix():
    assert extract_arxiv_id({"eprint": "arXiv:2410.03834"}) == "2410.03834"


def test_extract_arxiv_id_strips_version():
    assert extract_arxiv_id({"eprint": "2410.03834v2"}) == "2410.03834"


def test_extract_arxiv_id_from_journal_field():
    fields = {"journal": "arXiv preprint arXiv:2410.03834"}
    assert extract_arxiv_id(fields) == "2410.03834"


def test_extract_arxiv_id_from_journal_field_lowercase():
    fields = {"journal": "arXiv preprint arxiv:2303.17651"}
    assert extract_arxiv_id(fields) == "2303.17651"


def test_extract_arxiv_id_none_for_non_arxiv():
    assert extract_arxiv_id({"journal": "Nature"}) is None
    assert extract_arxiv_id({"title": "Some paper"}) is None


def test_is_truncated_et_al():
    assert _is_truncated("Smith, John et al.")
    assert _is_truncated("Smith, John and others")
    assert not _is_truncated("Smith, John and Doe, Jane")


def test_format_authors():
    names = ["Jane Doe", "John Smith", "Alice Lee"]
    assert _format_authors(names) == "Jane Doe and John Smith and Alice Lee"


def test_format_authors_skips_empty():
    assert _format_authors(["Alice", "", "Bob"]) == "Alice and Bob"
