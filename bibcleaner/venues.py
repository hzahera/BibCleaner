"""
Venue name normalization.

Maps every known abbreviation, DBLP shorthand, Semantic Scholar variant, and
user-entered shortcut to a single canonical full name.  Matching is done on a
stripped-down key (lowercase, no punctuation, no leading "proceedings of (the)").
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Canonical venue registry
# Each tuple: (canonical_full_name, [variant strings to match against])
# Variants are matched after the same normalization applied to inputs.
# ---------------------------------------------------------------------------

_REGISTRY: list[tuple[str, list[str]]] = [

    # ── Neural Information Processing Systems ───────────────────────────────
    ("Advances in Neural Information Processing Systems", [
        "neurips", "nips", "neural information processing systems",
        "advances in neural information processing systems",
        "neural inf process syst", "annual conference on neural information processing systems",
        "conference on neural information processing systems",
    ]),

    # ── ICML ────────────────────────────────────────────────────────────────
    ("International Conference on Machine Learning", [
        "icml", "international conference on machine learning",
        "intl conf machine learning", "int conf mach learn",
    ]),

    # ── ICLR ────────────────────────────────────────────────────────────────
    ("International Conference on Learning Representations", [
        "iclr", "international conference on learning representations",
        "intl conf learning representations",
    ]),

    # ── AAAI ────────────────────────────────────────────────────────────────
    ("AAAI Conference on Artificial Intelligence", [
        "aaai", "aaai conference on artificial intelligence",
        "national conference on artificial intelligence",
        "aaai conf artif intell",
    ]),

    # ── IJCAI ───────────────────────────────────────────────────────────────
    ("International Joint Conference on Artificial Intelligence", [
        "ijcai", "international joint conference on artificial intelligence",
        "intl joint conf artif intell",
    ]),

    # ── UAI ─────────────────────────────────────────────────────────────────
    ("Conference on Uncertainty in Artificial Intelligence", [
        "uai", "uncertainty in artificial intelligence",
        "conference on uncertainty in artificial intelligence",
    ]),

    # ── AISTATS ─────────────────────────────────────────────────────────────
    ("International Conference on Artificial Intelligence and Statistics", [
        "aistats",
        "international conference on artificial intelligence and statistics",
        "artif intell stat",
    ]),

    # ── ECML/PKDD ───────────────────────────────────────────────────────────
    ("European Conference on Machine Learning and Principles and Practice of Knowledge Discovery in Databases", [
        "ecml", "ecml pkdd", "ecml/pkdd",
        "european conference on machine learning",
        "machine learning and knowledge discovery in databases",
    ]),

    # ── ACL ─────────────────────────────────────────────────────────────────
    ("Annual Meeting of the Association for Computational Linguistics", [
        "acl", "annual meeting of the association for computational linguistics",
        "assoc comput linguist", "association for computational linguistics",
        "meeting of the association for computational linguistics",
    ]),

    # ── EMNLP ───────────────────────────────────────────────────────────────
    ("Conference on Empirical Methods in Natural Language Processing", [
        "emnlp", "empirical methods in natural language processing",
        "conference on empirical methods in natural language processing",
        "empir methods nat lang process",
    ]),

    # ── NAACL ───────────────────────────────────────────────────────────────
    ("Annual Conference of the North American Chapter of the Association for Computational Linguistics", [
        "naacl", "naacl-hlt",
        "north american chapter of the association for computational linguistics",
        "north american chapter of acl",
        "annual conference of the north american chapter of the association for computational linguistics",
    ]),

    # ── EACL ────────────────────────────────────────────────────────────────
    ("Conference of the European Chapter of the Association for Computational Linguistics", [
        "eacl",
        "european chapter of the association for computational linguistics",
        "conference of the european chapter of the association for computational linguistics",
    ]),

    # ── CoNLL ───────────────────────────────────────────────────────────────
    ("Conference on Computational Natural Language Learning", [
        "conll", "computational natural language learning",
        "conference on computational natural language learning",
    ]),

    # ── COLING ──────────────────────────────────────────────────────────────
    ("International Conference on Computational Linguistics", [
        "coling", "international conference on computational linguistics",
    ]),

    # ── CVPR ────────────────────────────────────────────────────────────────
    ("IEEE/CVF Conference on Computer Vision and Pattern Recognition", [
        "cvpr",
        "computer vision and pattern recognition",
        "ieee conference on computer vision and pattern recognition",
        "ieee/cvf conference on computer vision and pattern recognition",
        "conf comput vis pattern recognit",
    ]),

    # ── ICCV ────────────────────────────────────────────────────────────────
    ("IEEE/CVF International Conference on Computer Vision", [
        "iccv",
        "international conference on computer vision",
        "ieee international conference on computer vision",
        "ieee/cvf international conference on computer vision",
        "int conf comput vis",
    ]),

    # ── ECCV ────────────────────────────────────────────────────────────────
    ("European Conference on Computer Vision", [
        "eccv", "european conference on computer vision",
    ]),

    # ── KDD ─────────────────────────────────────────────────────────────────
    ("ACM SIGKDD Conference on Knowledge Discovery and Data Mining", [
        "kdd", "sigkdd",
        "acm sigkdd conference on knowledge discovery and data mining",
        "knowledge discovery and data mining",
        "acm sigkdd int conf knowl discov data min",
    ]),

    # ── WWW / TheWebConf ────────────────────────────────────────────────────
    ("ACM Web Conference", [
        "www", "thewebconf", "the web conference",
        "world wide web conference",
        "international world wide web conference",
        "acm web conference",
    ]),

    # ── SIGIR ───────────────────────────────────────────────────────────────
    ("ACM SIGIR Conference on Research and Development in Information Retrieval", [
        "sigir",
        "research and development in information retrieval",
        "acm sigir conference on research and development in information retrieval",
        "int acm sigir conf res dev inf retr",
    ]),

    # ── RecSys ──────────────────────────────────────────────────────────────
    ("ACM Conference on Recommender Systems", [
        "recsys", "recommender systems",
        "acm conference on recommender systems",
        "acm recsys",
    ]),

    # ── CIKM ────────────────────────────────────────────────────────────────
    ("ACM International Conference on Information and Knowledge Management", [
        "cikm",
        "acm international conference on information and knowledge management",
        "information and knowledge management",
    ]),

    # ── WSDM ────────────────────────────────────────────────────────────────
    ("ACM International Conference on Web Search and Data Mining", [
        "wsdm",
        "web search and data mining",
        "acm international conference on web search and data mining",
    ]),

    # ── ACM MM ──────────────────────────────────────────────────────────────
    ("ACM International Conference on Multimedia", [
        "acm mm", "acmmm", "multimedia",
        "acm international conference on multimedia",
        "acm multimedia",
    ]),

    # ── VLDB ────────────────────────────────────────────────────────────────
    ("Proceedings of the VLDB Endowment", [
        "vldb", "very large data bases",
        "proceedings of the vldb endowment",
        "proc vldb endow",
    ]),

    # ── SIGMOD ──────────────────────────────────────────────────────────────
    ("ACM SIGMOD International Conference on Management of Data", [
        "sigmod",
        "acm sigmod international conference on management of data",
        "management of data",
        "acm sigmod conf manag data",
    ]),

    # ── ICDE ────────────────────────────────────────────────────────────────
    ("IEEE International Conference on Data Engineering", [
        "icde",
        "ieee international conference on data engineering",
        "international conference on data engineering",
    ]),

    # ── INTERSPEECH ─────────────────────────────────────────────────────────
    ("Interspeech", [
        "interspeech",
        "annual conference of the international speech communication association",
    ]),

    # ── ICASSP ──────────────────────────────────────────────────────────────
    ("IEEE International Conference on Acoustics, Speech and Signal Processing", [
        "icassp",
        "ieee international conference on acoustics speech and signal processing",
        "ieee int conf acoust speech signal process",
    ]),

    # ─────────────────────────────────────────────────────────────────────────
    # Journals
    # ─────────────────────────────────────────────────────────────────────────

    ("Journal of Machine Learning Research", [
        "jmlr", "journal of machine learning research", "j mach learn res",
    ]),

    ("Transactions of the Association for Computational Linguistics", [
        "tacl",
        "transactions of the association for computational linguistics",
        "trans assoc comput linguist",
    ]),

    ("Transactions on Machine Learning Research", [
        "tmlr", "transactions on machine learning research",
    ]),

    ("IEEE Transactions on Pattern Analysis and Machine Intelligence", [
        "tpami", "pami",
        "ieee transactions on pattern analysis and machine intelligence",
        "ieee trans pattern anal mach intell",
    ]),

    ("IEEE Transactions on Neural Networks and Learning Systems", [
        "tnnls", "ieee transactions on neural networks and learning systems",
        "ieee trans neural netw learn syst",
    ]),

    ("Artificial Intelligence", [
        "artificial intelligence", "artif intell",
    ]),

    ("Neural Networks", [
        "neural networks", "neural netw",
    ]),

    ("Machine Learning", [
        "machine learning", "mach learn",
    ]),

    ("Nature Machine Intelligence", [
        "nature machine intelligence", "nat mach intell",
    ]),

    ("Nature Communications", [
        "nature communications", "nat commun",
    ]),
]

# ---------------------------------------------------------------------------
# Build lookup table
# ---------------------------------------------------------------------------

def _key(text: str) -> str:
    """Normalise a venue string to a match key."""
    t = text.lower()
    # Strip leading "proceedings of (the)" and similar
    t = re.sub(r"^(proceedings of (the )?|workshop on |the )", "", t)
    # Remove punctuation except spaces
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse whitespace
    return " ".join(t.split())


_LOOKUP: dict[str, str] = {}
for _canonical, _variants in _REGISTRY:
    for _v in _variants:
        _LOOKUP[_key(_v)] = _canonical
    # Also map the canonical name itself
    _LOOKUP[_key(_canonical)] = _canonical


def normalize_venue(name: str) -> Optional[str]:
    """Return the canonical full venue name for *name*, or None if unknown."""
    if not name:
        return None
    return _LOOKUP.get(_key(name))


def normalize_or_keep(name: str) -> str:
    """Return the canonical name if known, otherwise return name unchanged."""
    return normalize_venue(name) or name
