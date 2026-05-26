from .api import get_paper_data

def enrich_entry(entry):
    """Enrich a single BibTeX entry with Semantic Scholar data."""
    
    # In bibtexparser v2, entry.fields is a list of Field objects.
    # Let's extract them into a dictionary for easy checking.
    fields_dict = {f.key: f.value for f in entry.fields}
    
    arxiv_id = None
    if 'eprint' in fields_dict:
        arxiv_id = fields_dict['eprint']
    elif 'journal' in fields_dict and 'arxiv' in fields_dict['journal'].lower():
        parts = fields_dict['journal'].lower().split('arxiv:')
        if len(parts) > 1:
            arxiv_id = parts[1].strip()
            
    if not arxiv_id:
        return entry

    data = get_paper_data(arxiv_id)
    if not data:
        return entry

    # Create the new journal name if applicable
    new_journal = None
    if data.get('journal') and 'name' in data['journal']:
        new_journal = data['journal']['name']
    elif data.get('venue'):
        new_journal = data['venue']

    # Update entry type if it was a preprint but is now published
    if new_journal:
        entry.entry_type = 'article'

    # Safely modify the fields without explicitly importing the Field class
    # We do this by creating a new fields list, replacing matches, or adding new ones
    
    # Update or add Journal
    if new_journal:
        # Check if journal already exists, update its value
        journal_exists = False
        for f in entry.fields:
            if f.key == 'journal':
                f.value = new_journal
                journal_exists = True
                break
        
        # If it didn't exist, we can duplicate the structure of an existing field
        if not journal_exists and len(entry.fields) > 0:
            import copy
            new_field = copy.deepcopy(entry.fields[0])
            new_field.key = 'journal'
            new_field.value = new_journal
            entry.fields.append(new_field)

    # Update or add Year
    if data.get('year'):
        year_str = str(data['year'])
        year_exists = False
        for f in entry.fields:
            if f.key == 'year':
                f.value = year_str
                year_exists = True
                break
                
        if not year_exists and len(entry.fields) > 0:
            import copy
            new_field = copy.deepcopy(entry.fields[0])
            new_field.key = 'year'
            new_field.value = year_str
            entry.fields.append(new_field)
        
    return entry