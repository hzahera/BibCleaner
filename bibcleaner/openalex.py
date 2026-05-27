import json
import logging
import os
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

OPENALEX_WORKS = "https://api.openalex.org/works"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _normalize_doi(doi: str) -> str:
    doi = (doi or "").strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").strip()
    return doi.lower()


def _surname_set(authors: List[str]) -> set:
    out = set()
    for author in authors or []:
        author = (author or "").strip()
        if not author:
            continue
        if "," in author:
            out.add(author.split(",", 1)[0].strip().lower())
        else:
            parts = author.split()
            if parts:
                out.add(parts[-1].strip().lower())
    return out


class OpenAlexClient:
    def __init__(
        self,
        rate_limit_delay: float = 0.2,
        timeout: int = 10,
        cache_path: str = ".bibcleaner_openalex_cache.json",
        mailto: Optional[str] = None,
    ):
        self.rate_limit_delay = rate_limit_delay
        self.timeout = timeout
        self.cache_path = cache_path
        self.mailto = mailto
        self.session = requests.Session()
        self.last_request_time = 0.0
        self.cache = self._load_cache()

    def _load_cache(self) -> Dict:
        if self.cache_path and os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.warning("Could not read OpenAlex cache; starting fresh")
        return {}

    def _save_cache(self):
        if not self.cache_path:
            return
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Could not save OpenAlex cache: {e}")

    def _rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def _request(self, params: Dict) -> Optional[Dict]:
        self._rate_limit()
        try:
            if self.mailto:
                params = dict(params)
                params["mailto"] = self.mailto
            resp = self.session.get(OPENALEX_WORKS, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(f"OpenAlex HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        except requests.RequestException as e:
            logger.warning(f"OpenAlex request failed: {e}")
            return None

    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict]:
        title = (title or "").strip()
        if not title:
            return []
        cache_key = f"title:{_normalize_text(title)}:{max_results}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        params = {"search": title, "per-page": max_results}
        data = self._request(params)
        works = data.get("results", []) if data else []
        self.cache[cache_key] = works
        self._save_cache()
        return works

    def best_match(
        self,
        title: str,
        authors: Optional[List[str]] = None,
        year: Optional[str] = None,
    ) -> Optional[Dict]:
        candidates = self.search_by_title(title, max_results=5)
        if not candidates:
            return None

        title_norm = _normalize_text(title)
        input_surnames = _surname_set(authors or [])
        year_str = str(year).strip() if year else ""

        best, best_score = None, 0.0

        for work in candidates:
            work_title = work.get("display_name") or work.get("title") or ""
            sim = SequenceMatcher(None, title_norm, _normalize_text(work_title)).ratio()

            work_year = str(work.get("publication_year") or "")
            year_score = 0.0
            if year_str and work_year:
                if work_year == year_str:
                    year_score = 1.0
                elif abs(int(work_year) - int(year_str)) <= 1:
                    year_score = 0.5

            work_authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in (work.get("authorships") or [])
            ]
            overlap = len(input_surnames & _surname_set(work_authors))
            author_score = min(overlap / 2.0, 1.0) if input_surnames else 0.0

            score = 0.7 * sim + 0.2 * year_score + 0.1 * author_score
            if score > best_score:
                best_score = score
                best = work

        return best if best_score >= 0.88 else None

    def normalize_work(self, work: Dict) -> Optional[Dict]:
        if not work:
            return None

        source = ((work.get("primary_location") or {}).get("source") or {})
        biblio = work.get("biblio") or {}
        authorships = work.get("authorships") or []

        authors = [
            (a.get("author") or {}).get("display_name")
            for a in authorships
            if (a.get("author") or {}).get("display_name")
        ]

        title = work.get("display_name") or work.get("title")
        year = work.get("publication_year")
        doi = work.get("doi") or (work.get("ids") or {}).get("doi")
        source_name = source.get("display_name")
        work_type = (work.get("type_crossref") or work.get("type") or "").lower()

        first_page = biblio.get("first_page")
        last_page = biblio.get("last_page")
        pages = None
        if first_page and last_page:
            pages = f"{first_page}--{last_page}"
        elif first_page:
            pages = str(first_page)

        out = {
            "title": title,
            "year": str(year) if year else None,
            "doi": _normalize_doi(doi) if doi else None,
            "authors": authors,
            "volume": biblio.get("volume"),
            "number": biblio.get("issue"),
            "pages": pages,
            "journal": None,
            "booktitle": None,
            "entry_type": None,
        }

        if source_name:
            if "proceedings" in work_type or "conference" in work_type:
                out["entry_type"] = "inproceedings"
                out["booktitle"] = source_name
            else:
                out["entry_type"] = "article"
                out["journal"] = source_name

        return out
