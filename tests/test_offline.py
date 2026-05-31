"""Offline (no-network) tests for the LaTeX-friendly cleaning features."""

from bibtexparser.model import Entry, Field

from bibcleaner.latex import protect_title_caps
from bibcleaner.dedup import deduplicate
from bibcleaner.citations import collect_cited_keys, prune_unused, missing_citations


def _entry(entry_type, key, **fields):
    return Entry(entry_type, key, [Field(k, v) for k, v in fields.items()])


# --------------------------------------------------------------------------
# protect_title_caps
# --------------------------------------------------------------------------

def test_protect_acronyms_and_intercaps():
    assert protect_title_caps("BERT: A Method for ImageNet") == "{BERT}: A Method for {ImageNet}"


def test_protect_leaves_plain_title_case():
    assert protect_title_caps("Attention Is All You Need") == "Attention Is All You Need"


def test_protect_is_idempotent():
    once = protect_title_caps("Scaling GPT-4 on TPUs")
    assert once == protect_title_caps(once)


def test_protect_skips_braced_and_math():
    assert protect_title_caps("{BERT} and $O(n)$ cost") == "{BERT} and $O(n)$ cost"


def test_protect_handles_empty():
    assert protect_title_caps("") == ""


# --------------------------------------------------------------------------
# deduplicate
# --------------------------------------------------------------------------

def test_dedup_prefers_published_over_preprint():
    pre = _entry("misc", "selfrefine_arxiv", title="Self-Refine", eprint="2303.17651")
    pub = _entry(
        "inproceedings", "selfrefine_neurips",
        title="Self-Refine", eprint="2303.17651",
        booktitle="Advances in Neural Information Processing Systems (NeurIPS)",
        year="2023",
    )
    kept, remap = deduplicate([pre, pub])
    assert len(kept) == 1
    assert kept[0].key == "selfrefine_neurips"
    assert remap == {"selfrefine_arxiv": "selfrefine_neurips"}


def test_dedup_matches_on_doi():
    a = _entry("article", "a", title="Paper One", doi="10.1/x")
    b = _entry("article", "b", title="Paper One", doi="https://doi.org/10.1/X")
    kept, remap = deduplicate([a, b])
    assert len(kept) == 1 and remap == {"b": "a"}


def test_dedup_merges_missing_fields():
    a = _entry("article", "a", title="P", doi="10.1/x", year="2024")
    b = _entry("article", "b", title="P", doi="10.1/x", journal="JMLR")
    kept, _ = deduplicate([a, b])
    fields = {f.key: f.value for f in kept[0].fields}
    assert fields.get("journal") == "JMLR" and fields.get("year") == "2024"


def test_dedup_does_not_carry_arxiv_journal_into_inproceedings():
    pre = _entry("misc", "a", title="P", eprint="2303.17651",
                 journal="arXiv preprint arXiv:2303.17651")
    pub = _entry("inproceedings", "b", title="P", eprint="2303.17651",
                 booktitle="NeurIPS", year="2023")
    kept, _ = deduplicate([pre, pub])
    fields = {f.key: f.value for f in kept[0].fields}
    assert kept[0].key == "b"
    assert "journal" not in fields


def test_dedup_keeps_distinct_entries():
    a = _entry("article", "a", title="Alpha", year="2020")
    b = _entry("article", "b", title="Beta", year="2021")
    kept, remap = deduplicate([a, b])
    assert len(kept) == 2 and remap == {}


# --------------------------------------------------------------------------
# citations
# --------------------------------------------------------------------------

def test_collect_keys_from_tex(tmp_path):
    tex = tmp_path / "paper.tex"
    tex.write_text(r"Text \citep{a,b} more \cite{c} and \autocite[see][p.~2]{d}.")
    assert collect_cited_keys([str(tex)]) == {"a", "b", "c", "d"}


def test_collect_keys_from_aux(tmp_path):
    aux = tmp_path / "paper.aux"
    aux.write_text("\\citation{vaswani2017}\n\\citation{devlin2019}\n")
    assert collect_cited_keys([str(aux)]) == {"vaswani2017", "devlin2019"}


def test_nocite_star_keeps_all(tmp_path):
    tex = tmp_path / "p.tex"
    tex.write_text(r"\nocite{*}")
    cited = collect_cited_keys([str(tex)])
    entries = [_entry("article", "a", title="A"), _entry("article", "b", title="B")]
    kept, dropped = prune_unused(entries, cited)
    assert len(kept) == 2 and dropped == []


def test_prune_and_missing():
    entries = [_entry("article", "used", title="U"), _entry("article", "unused", title="X")]
    cited = {"used", "ghost"}
    kept, dropped = prune_unused(entries, cited)
    assert [e.key for e in kept] == ["used"]
    assert dropped == ["unused"]
    assert missing_citations(entries, cited) == ["ghost"]
