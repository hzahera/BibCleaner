import requests
from requests.exceptions import RequestException

S2_URL = "https://api.semanticscholar.org/graph/v1/paper/"

def fetch_by_arxiv(arxiv_id: str):
    url = f"{S2_URL}ARXIV:{arxiv_id}"
    params = {
        "fields": "title,authors,year,venue,externalIds"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
    except RequestException:
        return None

    return r.json()
