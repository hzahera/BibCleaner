import os
import re
import time
import logging
import requests

logger = logging.getLogger(__name__)

_SS_FIELDS = (
    "title,authors,year,venue,journal,publicationVenue,externalIds,publicationTypes"
)

# Semantic Scholar public API: ~1 req/sec without a key, much higher with one.
# We enforce a conservative gap so the whole-bib run stays inside quota.
_MIN_REQUEST_GAP = 3.0  # seconds (safe for the anonymous tier)
_last_request_time: float = 0.0


def _throttle():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - elapsed)
    _last_request_time = time.time()


def fetch_by_arxiv_id(arxiv_id: str, retries: int = 3) -> dict | None:
    """Fetch paper metadata from Semantic Scholar using an arXiv ID.

    Set the S2_API_KEY environment variable to use a higher-rate-limit key.
    """
    clean_id = re.sub(r"^arxiv:", "", arxiv_id.strip(), flags=re.IGNORECASE)
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{clean_id}"
    params = {"fields": _SS_FIELDS}

    api_key = os.environ.get("S2_API_KEY")
    if not api_key:
        logger.warning("No Semantic Scholar API key found. Request failed.")
        return None
    headers = {"x-api-key": api_key} if api_key else {}

    for attempt in range(retries):
        _throttle()
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = 10 * (2**attempt)  # 10s, 20s, 40s
                logger.warning(f"Semantic Scholar rate-limited; retrying in {wait}s")
                time.sleep(wait)
            elif resp.status_code == 404:
                logger.debug(f"arXiv:{arxiv_id} not found in Semantic Scholar")
                break
            else:
                logger.warning(
                    f"Semantic Scholar HTTP {resp.status_code} for arXiv:{arxiv_id}"
                )
                break
        except requests.RequestException as exc:
            logger.warning(f"Semantic Scholar request failed: {exc}")
            break
    return None
