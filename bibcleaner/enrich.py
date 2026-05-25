import re
from tqdm import tqdm
from .api import fetch_by_arxiv


def extract_arxiv_id(text):
    if not text:
        return None
    match = re.search(r"(\d{4}\.\d{4,5})", text)
    return match.group(1) if match else None


def format_authors(authors):
    return " and ".join([a["name"] for a in authors])


def upgrade_entry(entry):
    arxiv_id = extract_arxiv_id(entry.get("journal", ""))

    if not arxiv_id:
        return entry

    data = fetch_by_arxiv(arxiv_id)
    if not data:
        return entry

    if data.get("venue"):
        entry["journal"] = data["venue"]

    if data.get("authors"):
        entry["author"] = format_authors(data["authors"])

    return entry


def process_entries(db):
    for i, entry in enumerate(tqdm(db.entries, desc="Cleaning entries", unit="entry")):
        db.entries[i] = upgrade_entry(entry)
    return db
