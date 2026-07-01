import os
import shutil
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel
from typing import Optional
from app.database import get_db
from app.models.paper import ResearchPaper
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
):
    query = select(ResearchPaper)

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
    sort_map = {
        "created_at": ResearchPaper.created_at.desc(),
        "title": ResearchPaper.title.asc(),
        "year": ResearchPaper.year.desc(),
    }
    query = query.order_by(sort_map.get(sort, ResearchPaper.created_at.desc()))

    result = await db.execute(query)
    papers = result.scalars().all()
    return papers


@router.post("")
async def upload_paper(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
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
    )

    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    # Build embeddings automatically on upload
    try:
        from app.services.embedding_service import check_embed_available, build_paper_chunks
        embed_ok = await check_embed_available()
        if embed_ok and paper.extracted_text:
            print(f"[Upload] Automatically building chunks and embeddings for paper {paper.id}...")
            await build_paper_chunks(paper.id, paper.extracted_text, db)
    except Exception as e:
        print(f"[Upload] Failed to build embeddings automatically: {e}")

    return paper


@router.get("/export-citations")
async def export_citations(
    folder_id: Optional[str] = None,
    format: Optional[str] = "apa",
    db: AsyncSession = Depends(get_db)
):
    query = select(ResearchPaper)
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
async def get_paper_citation(paper_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    
    from app.services.citation_service import generate_citations
    return generate_citations(paper.title or "Untitled", paper.authors or "", paper.journal or "", paper.year)


@router.get("/{paper_id}/slides")
async def get_paper_slides(paper_id: str, db: AsyncSession = Depends(get_db)):
    """Return extracted slide images and text for a PPTX paper."""
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
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
async def get_paper(paper_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@router.patch("/{paper_id}")
async def update_paper(
    paper_id: str,
    update: PaperUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
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
async def delete_paper(paper_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
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
