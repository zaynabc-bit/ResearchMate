import os
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.paper import ResearchPaper
from app.models.search import DiscoverSearch
from app.api.auth import get_current_user_id
from app.services.pdf_service import extract_text_from_file, get_filename_title
from dotenv import load_dotenv

load_dotenv()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
router = APIRouter()


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    authors: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    custom_header: Optional[str] = None
    notes: Optional[str] = None
    is_favourite: Optional[bool] = None
    folder_id: Optional[str] = None


@router.get("")
async def list_papers(
    folder_id: Optional[str] = None,
    favourites: Optional[bool] = None,
    sort: Optional[str] = "created_at",
    q: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    query = select(ResearchPaper).where(ResearchPaper.user_id == user_id)

    if folder_id:
        query = query.where(ResearchPaper.folder_id == folder_id)
    if favourites:
        query = query.where(ResearchPaper.is_favourite == True)
    if q:
        search = f"%{q}%"
        query = query.where(
            or_(
                ResearchPaper.title.ilike(search),
                ResearchPaper.authors.ilike(search),
                ResearchPaper.extracted_text.ilike(search),
                ResearchPaper.summary.ilike(search),
                ResearchPaper.notes.ilike(search),
                ResearchPaper.keywords.ilike(search),
            )
        )

    # Sorting
    # We use a tuple for the sorting criteria so we can pass multiple order_by clauses to SQLAlchemy
    sort_map = {
        "created_at": (ResearchPaper.created_at.desc(),),
        "title": (func.lower(ResearchPaper.title).asc(), ResearchPaper.created_at.desc()),
        "author": (func.lower(ResearchPaper.authors).asc(), ResearchPaper.created_at.desc()),
        "year_desc": (ResearchPaper.year.desc().nullslast(), ResearchPaper.created_at.desc()),
        "year_asc": (ResearchPaper.year.asc().nullsfirst(), ResearchPaper.created_at.desc()),
        "pages_desc": (ResearchPaper.page_count.desc().nullslast(), ResearchPaper.created_at.desc()),
        "pages_asc": (ResearchPaper.page_count.asc().nullsfirst(), ResearchPaper.created_at.desc()),
        "read_count": (ResearchPaper.read_count.desc(), ResearchPaper.created_at.desc()),
        "last_opened": (ResearchPaper.last_opened.desc().nullslast(), ResearchPaper.created_at.desc()),
    }
    
    sort_criteria = sort_map.get(sort, (ResearchPaper.created_at.desc(),))
    query = query.order_by(*sort_criteria)

    result = await db.execute(query)
    papers = result.scalars().all()
    return papers


@router.post("")
async def upload_paper(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    allowed_exts = {".pdf", ".docx", ".doc", ".rtf", ".txt", ".md", ".pptx", ".csv", ".xlsx", ".xls"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, DOCX, DOC, RTF, TXT, MD, PPTX, CSV, and Excel files are accepted"
        )

    # Save file
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    filename = f"{file_id}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Extract document data (pass paper_id for PPTX image extraction)
    doc_data = extract_text_from_file(file_path, paper_id=file_id)

    # Determine title: fallback to filename if empty or generic PPTX placeholder
    extracted_title = doc_data["title"]
    if not extracted_title or extracted_title.lower().strip() == "insert title here":
        final_title = get_filename_title(file.filename)
    else:
        final_title = extracted_title

    # Create paper record
    paper = ResearchPaper(
        id=file_id,
        title=final_title,
        authors=doc_data["authors"],
        abstract=doc_data["abstract"],
        extracted_text=doc_data["text"],
        file_url=file_path,
        file_size=doc_data["file_size"],
        page_count=doc_data["page_count"],
        summary_status="none",
        user_id=user_id,
    )

    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    # Build embeddings automatically on upload
    try:
        from app.services.embedding_service import check_embed_available, build_paper_chunks
        embed_ok = await check_embed_available()
        if embed_ok and paper.extracted_text:
            if len(paper.extracted_text) > 150000:
                print(f"[Upload] Skipping auto-embedding for {paper.id} because it exceeds 150,000 chars (likely a textbook).")
            else:
                print(f"[Upload] Automatically building chunks and embeddings for paper {paper.id}...")
                await build_paper_chunks(paper.id, paper.extracted_text, db)
    except Exception as e:
        print(f"[Upload] Failed to build embeddings automatically: {e}")

    return paper


@router.get("/export-citations")
async def export_citations(
    folder_id: Optional[str] = None,
    format: Optional[str] = "apa",
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    query = select(ResearchPaper).where(ResearchPaper.user_id == user_id)
    if folder_id and folder_id != "all":
        query = query.where(ResearchPaper.folder_id == folder_id)
        
    result = await db.execute(query)
    papers = result.scalars().all()
    
    if not papers:
        return {"citations": ""}
        
    from app.services.citation_service import generate_citations
    
    def get_sort_key(p):
        author_str = p.authors or ""
        if author_str:
            import re
            normalized = re.sub(r'\s+and\s+', ', ', author_str, flags=re.IGNORECASE)
            parts = [part.strip() for part in re.split(r'[;,&]', normalized) if part.strip()]
            if parts:
                first = parts[0]
                if ',' in first:
                    return first.split(',')[0].strip().lower()
                else:
                    subparts = first.split()
                    if subparts:
                        return subparts[-1].lower()
        return (p.title or "").lower()
        
    sorted_papers = sorted(papers, key=get_sort_key)
    
    citations_list = []
    format_lower = format.lower()
    
    for p in sorted_papers:
        c = generate_citations(p.title or "Untitled", p.authors or "", p.journal or "", p.year)
        if format_lower == "bibtex":
            citations_list.append(c["bibtex"])
        elif format_lower == "harvard":
            citations_list.append(c["harvard"])
        else:
            citations_list.append(c["apa"])
            
    separator = "\n\n"
    return {"citations": separator.join(citations_list)}


@router.get("/{paper_id}/citation")
async def get_paper_citation(paper_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id, ResearchPaper.user_id == user_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    from app.services.citation_service import generate_citations
    return generate_citations(paper.title or "Untitled", paper.authors or "", paper.journal or "", paper.year)


@router.get("/{paper_id}/slides")
async def get_paper_slides(paper_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """Return extracted slide images and text for a PPTX paper."""
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id, ResearchPaper.user_id == user_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    upload_dir = os.getenv("UPLOAD_DIR", "uploads")
    slides_dir = os.path.join(upload_dir, "slides", paper_id)
    if not os.path.isdir(slides_dir):
        return []

    # Group images by slide number (slide_001_img_1.png -> slide 1)
    from collections import defaultdict
    import re
    slide_map = defaultdict(list)
    for fname in sorted(os.listdir(slides_dir)):
        m = re.match(r"slide_(\d+)_img_", fname)
        if m:
            slide_num = int(m.group(1))
            slide_map[slide_num].append(f"/uploads/slides/{paper_id}/{fname}")

    return [
        {"slide_num": snum, "images": imgs}
        for snum, imgs in sorted(slide_map.items())
    ]


@router.get("/{paper_id}")
async def get_paper(paper_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id, ResearchPaper.user_id == user_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
        
    paper.read_count = (paper.read_count or 0) + 1
    paper.last_opened = func.now()
    await db.commit()
    await db.refresh(paper)
    
    return paper


@router.patch("/{paper_id}")
async def update_paper(
    paper_id: str,
    update: PaperUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id, ResearchPaper.user_id == user_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    old_title = paper.title
    old_authors = paper.authors
    old_custom_header = paper.custom_header

    for field, value in update.model_dump(exclude_none=True).items():
        setattr(paper, field, value)

    await db.commit()
    await db.refresh(paper)

    # Re-embed if text-affecting metadata has changed
    metadata_changed = (
        paper.title != old_title or
        paper.authors != old_authors or
        paper.custom_header != old_custom_header
    )
    if metadata_changed:
        from app.services.embedding_service import has_chunks, build_paper_chunks
        if await has_chunks(paper_id, db):
            print(f"[Embed] Re-building chunks for paper {paper_id} due to metadata update...")
            await build_paper_chunks(paper_id, paper.extracted_text, db)

    return paper


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id, ResearchPaper.user_id == user_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Delete file from disk
    if os.path.exists(paper.file_url):
        os.remove(paper.file_url)

    # Delete extracted slide images if PPTX
    upload_dir = os.getenv("UPLOAD_DIR", "uploads")
    slides_dir = os.path.join(upload_dir, "slides", paper_id)
    if os.path.isdir(slides_dir):
        shutil.rmtree(slides_dir)

    await db.delete(paper)
    await db.commit()
    return {"message": "Paper deleted"}

@router.get("/references/search")
async def search_web_references(q: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    import urllib.request
    import urllib.parse
    import json
    import re
    
    if not q:
        return []

    # Save to history
    result = await db.execute(select(DiscoverSearch).where(DiscoverSearch.user_id == user_id, DiscoverSearch.query == q))
    existing = result.scalar_one_or_none()
    if existing:
        existing.created_at = func.now()
    else:
        new_search = DiscoverSearch(user_id=user_id, query=q)
        db.add(new_search)
    await db.commit()

    # Clean up query slightly
    search_query = re.sub(r'[^\w\s]', '', q)
    safe_query = urllib.parse.quote(search_query)
    url = f"https://api.crossref.org/works?query={safe_query}&select=title,author,URL,abstract,published-print&rows=10"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ResearchMate/1.0 (mailto:admin@example.com)'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            items = data.get("message", {}).get("items", [])
            
            references = []
            for item in items:
                authors = []
                for a in item.get("author", []):
                    if "family" in a:
                        authors.append(f"{a.get('given', '')} {a['family']}".strip())
                author_str = ", ".join(authors) if authors else "Unknown Authors"
                
                year = ""
                try:
                    year = str(item.get("published-print", {}).get("date-parts", [[None]])[0][0])
                except:
                    pass
                
                title = item.get("title", ["Unknown Title"])[0]
                url_val = item.get("URL", "")
                abstract = item.get("abstract", "")
                
                if abstract:
                    abstract = re.sub(r'<[^>]+>', '', abstract)
                    if abstract.startswith('jats:p'):
                        abstract = abstract[6:]
                
                references.append({
                    "title": title,
                    "authors": author_str,
                    "year": year,
                    "url": url_val,
                    "abstract": abstract
                })
            return references
    except Exception as e:
        print(f"CrossRef API Error: {e}")
        return []

@router.get("/{paper_id}/references")
async def get_paper_references(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    query = select(ResearchPaper).where(ResearchPaper.id == paper_id, ResearchPaper.user_id == user_id)
    result = await db.execute(query)
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    import urllib.request
    import urllib.parse
    import json
    import re
    
    # Use paper title or a core sentence from the summary
    search_query = paper.title or paper.filename or "research"
    # Clean up query slightly to improve search
    search_query = re.sub(r'[^\w\s]', '', search_query)
    
    safe_query = urllib.parse.quote(search_query)
    url = f"https://api.crossref.org/works?query={safe_query}&select=title,author,URL,abstract,published-print&rows=5"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'ResearchMate/1.0 (mailto:admin@example.com)'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            items = data.get("message", {}).get("items", [])
            
            references = []
            for item in items:
                # Format authors
                authors = []
                for a in item.get("author", []):
                    if "family" in a:
                        authors.append(f"{a.get('given', '')} {a['family']}".strip())
                author_str = ", ".join(authors) if authors else "Unknown Authors"
                
                # Format year
                year = ""
                try:
                    year = str(item.get("published-print", {}).get("date-parts", [[None]])[0][0])
                except:
                    pass
                
                title = item.get("title", ["Unknown Title"])[0]
                url_val = item.get("URL", "")
                abstract = item.get("abstract", "")
                
                # Clean up abstract if it has HTML tags
                if abstract:
                    abstract = re.sub(r'<[^>]+>', '', abstract)
                    if abstract.startswith('jats:p'):
                        abstract = abstract[6:]
                
                references.append({
                    "title": title,
                    "authors": author_str,
                    "year": year,
                    "url": url_val,
                    "abstract": abstract
                })
            return references
    except Exception as e:
        print(f"CrossRef API Error: {e}")
        return []

@router.get("/references/search/history")
async def get_recent_searches(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(
        select(DiscoverSearch)
        .where(DiscoverSearch.user_id == user_id)
        .order_by(DiscoverSearch.created_at.desc())
        .limit(5)
    )
    searches = result.scalars().all()
    return [s.query for s in searches]
