import re

def split_authors(authors_str: str) -> list:
    """Split authors string into individual author elements safely."""
    if not authors_str:
        return []
    
    # Step 1: Split on major separators (semicolon, "and", ampersand)
    parts = re.split(r';|\s+and\s+|\s*&\s*', authors_str, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]
    
    # Step 2: If we only got 1 part, but there is a comma, check if we should split by comma
    if len(parts) == 1 and ',' in parts[0]:
        subparts = [sp.strip() for sp in parts[0].split(',') if sp.strip()]
        # If any subpart has a space, it's like "John Doe, Jane Smith", so comma separates authors
        if any(' ' in sp for sp in subparts):
            parts = subparts
            
    return parts

def parse_single_author(author_part: str) -> tuple:
    """Extract (lastname, firstname_or_initials) from a single author string."""
    if ',' in author_part:
        subparts = [sp.strip() for sp in author_part.split(',')]
        last = subparts[0]
        first = subparts[1] if len(subparts) > 1 else ""
        return last, first
    else:
        subparts = author_part.split()
        if len(subparts) > 1:
            last = subparts[-1]
            first = " ".join(subparts[:-1])
            return last, first
        else:
            return author_part, ""

def format_apa_author(authors_str: str) -> str:
    """Format authors list to APA style (Last, F. M. & Last2, F. M.)."""
    author_parts = split_authors(authors_str)
    if not author_parts:
        return "Unknown Author"
        
    formatted_authors = []
    for part in author_parts:
        last, first = parse_single_author(part)
        if first:
            initials = " ".join(f"{n[0]}." for n in first.split() if n)
            formatted_authors.append(f"{last}, {initials}")
        else:
            formatted_authors.append(last)
                
    if len(formatted_authors) == 1:
        return formatted_authors[0]
    elif len(formatted_authors) == 2:
        return f"{formatted_authors[0]} & {formatted_authors[1]}"
    else:
        return ", ".join(formatted_authors[:-1]) + f", & {formatted_authors[-1]}"

def format_harvard_author(authors_str: str) -> str:
    """Format authors list to Harvard style (Last, F.M. and Last2, F.M.)."""
    apa = format_apa_author(authors_str)
    return apa.replace(" & ", " and ").replace(", & ", " and ")

def format_bibtex_author(authors_str: str) -> str:
    """Format authors list to BibTeX style (Last1, First1 and Last2, First2)."""
    author_parts = split_authors(authors_str)
    if not author_parts:
        return "Unknown Author"
        
    formatted_authors = []
    for part in author_parts:
        last, first = parse_single_author(part)
        if first:
            formatted_authors.append(f"{last}, {first}")
        else:
            formatted_authors.append(last)
            
    return " and ".join(formatted_authors)

def get_citekey(title: str, authors_str: str, year: int) -> str:
    """Generate a clean BibTeX citation key (e.g. smith2026)."""
    author_parts = split_authors(authors_str)
    last_name = "unknown"
    if author_parts:
        last, _ = parse_single_author(author_parts[0])
        last_name = last
                    
    last_name = "".join(c for c in last_name if c.isalnum()).lower()
    yr = str(year) if year else "nodate"
    return f"{last_name}{yr}"

def generate_citations(title: str, authors: str, journal: str, year: int) -> dict:
    """Generate citations in APA, Harvard, and BibTeX formats."""
    apa_authors = format_apa_author(authors)
    apa_year = f"({year})" if year else "(n.d.)"
    if journal:
        apa = f"{apa_authors} {apa_year}. {title}. *{journal}*."
    else:
        apa = f"{apa_authors} {apa_year}. *{title}*."
        
    harvard_authors = format_harvard_author(authors)
    harvard_year = f"{year}" if year else "n.d."
    if journal:
        harvard = f"{harvard_authors}, {harvard_year}. {title}. *{journal}*."
    else:
        harvard = f"{harvard_authors}, {harvard_year}. *{title}*."
        
    bib_authors = format_bibtex_author(authors)
    citekey = get_citekey(title, authors, year)
    
    bibtex = f"@article{{{citekey},\n"
    bibtex += f"  author = {{{bib_authors}}},\n"
    bibtex += f"  title = {{{title}}},\n"
    if journal:
        bibtex += f"  journal = {{{journal}}},\n"
    if year:
        bibtex += f"  year = {{{year}}}\n"
    else:
        bibtex += f"  year = {{n.d.}}\n"
    bibtex += "}"
    
    return {
        "apa": apa,
        "harvard": harvard,
        "bibtex": bibtex
    }
