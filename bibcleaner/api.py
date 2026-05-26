import time
import requests
import logging

def get_paper_data(arxiv_id, retries=3, backoff_factor=2):
    """Fetch paper metadata from Semantic Scholar using arXiv ID with rate limit handling."""
    clean_id = arxiv_id.replace("arXiv:", "").replace("ARXIV:", "")
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:{clean_id}"
    params = {"fields": "title,authors,year,venue,journal,url"}
    
    for attempt in range(retries):
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:
            sleep_time = backoff_factor ** attempt
            logging.warning(f"Rate limited. Retrying in {sleep_time} seconds...")
            time.sleep(sleep_time)
        else:
            logging.error(f"Failed to fetch data for {arxiv_id}: HTTP {response.status_code}")
            break
            
    return None