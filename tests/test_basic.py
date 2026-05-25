"""Basic tests for bibcleaner."""

from bibcleaner.enrich import extract_arxiv_id, format_authors


def test_extract_arxiv_id():
    assert extract_arxiv_id("arXiv:2101.00001") == "2101.00001"
    assert extract_arxiv_id("no id here") is None


def test_format_authors():
    authors = [{"name": "Jane Doe"}, {"name": "John Smith"}]
    assert format_authors(authors) == "Jane Doe and John Smith"
