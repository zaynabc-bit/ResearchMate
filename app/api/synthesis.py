import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.api.auth import get_current_user_id
from app.models.synthesis import SynthesisReport
from app.models.paper import ResearchPaper
from app.models.chunk import PaperChunk
from app.services.ai_service import generate_synthesis

router = APIRouter()

class SynthesisRequest(BaseModel):
    title: Optional[str] = "Untitled Report"
    paper_ids: List[str]
    manual_text: Optional[str] = ""
    style: str
    custom_prompt: Optional[str] = ""

@router.post("/generate")
async def generate_report(req: SynthesisRequest, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    combined_text = ""
    
    # 1. Fetch text from selected library papers
    if req.paper_ids:
        # Get all chunks for the selected papers
        result = await db.execute(select(PaperChunk).where(PaperChunk.paper_id.in_(req.paper_ids)).order_by(PaperChunk.paper_id, PaperChunk.chunk_index))
        chunks = result.scalars().all()
        
        current_paper_id = None
        for chunk in chunks:
            if chunk.paper_id != current_paper_id:
                # Add a separator and paper title (if available, we could fetch paper title, but for simplicity we just separate chunks)
                combined_text += f"\n\n--- Source ID: {chunk.paper_id} ---\n\n"
                current_paper_id = chunk.paper_id
            combined_text += f"{chunk.text}\n"

    # 2. Add manual text
    if req.manual_text:
        combined_text += f"\n\n--- Manual Input ---\n\n{req.manual_text}\n"
        
    if not combined_text.strip():
        raise HTTPException(status_code=400, detail="No source text provided for synthesis.")
        
    # Limit combined text to ~10k words to prevent context overflow, though Qwen2.5 can handle 32k.
    # We will limit to 50000 chars
    combined_text = combined_text[:50000]
        
    try:
        # 3. Call AI
        report_content = await generate_synthesis(combined_text, req.style, req.custom_prompt)
        
        # 4. Extract synthetic title from the generated content
        title = req.title
        lines = report_content.split("\n")
        for line in lines[:5]:
            if line.startswith("# "):
                title = line.replace("# ", "").strip()
                break
        
        # 5. Save to DB
        report = SynthesisReport(
            user_id=user_id,
            title=title,
            content=report_content,
            style=req.style,
            custom_prompt=req.custom_prompt
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        
        return {
            "id": report.id,
            "title": report.title,
            "content": report.content,
            "style": report.style,
            "created_at": report.created_at
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_synthesis_history(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(
        select(SynthesisReport)
        .where(SynthesisReport.user_id == user_id)
        .order_by(SynthesisReport.created_at.desc())
    )
    reports = result.scalars().all()
    return [{
        "id": r.id,
        "title": r.title,
        "content": r.content,
        "style": r.style,
        "created_at": r.created_at
    } for r in reports]
