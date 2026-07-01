import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
from app.database import get_db
from app.models.paper import ResearchPaper
from app.models.comparison import PaperComparison
from app.services.ai_service import generate_comparison, generate_summary
from app.api.auth import get_current_user_id

router = APIRouter()

class ComparisonGenerateRequest(BaseModel):
    paper_a_id: str
    paper_b_id: str
    mode: Optional[str] = "fast"
    api_keys: Optional[dict] = {}

class ComparisonSaveRequest(BaseModel):
    title: str
    paper_a_id: str
    paper_b_id: str
    comparison_data: dict

class ComparisonRenameRequest(BaseModel):
    title: str

@router.post("/generate")
async def api_generate_comparison(
    request: ComparisonGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    # Fetch paper A
    res_a = await db.execute(select(ResearchPaper).where(ResearchPaper.id == request.paper_a_id, ResearchPaper.user_id == user_id))
    paper_a = res_a.scalar_one_or_none()
    
    # Fetch paper B
    res_b = await db.execute(select(ResearchPaper).where(ResearchPaper.id == request.paper_b_id, ResearchPaper.user_id == user_id))
    paper_b = res_b.scalar_one_or_none()
    
    if not paper_a or not paper_b:
        raise HTTPException(status_code=404, detail="One or both papers not found")

    def ensure_str(val):
        if isinstance(val, list):
            return "\n- " + "\n- ".join(str(v) for v in val)
        return str(val) if val else ""

    # If Paper A summary doesn't exist, generate it first
    if not paper_a.summary or paper_a.summary_status != "done":
        if not paper_a.extracted_text:
            raise HTTPException(status_code=400, detail=f"Paper '{paper_a.title}' text is not extracted")
        try:
            summary_a_data = await generate_summary(paper_a.extracted_text, mode=request.mode)
            paper_a.summary = ensure_str(summary_a_data.get("summary", ""))
            paper_a.research_aim = ensure_str(summary_a_data.get("research_aim", ""))
            paper_a.methodology = ensure_str(summary_a_data.get("methodology", ""))
            paper_a.key_findings = ensure_str(summary_a_data.get("key_findings", ""))
            paper_a.limitations = ensure_str(summary_a_data.get("limitations", ""))
            paper_a.strengths = ensure_str(summary_a_data.get("strengths", ""))
            paper_a.weaknesses = ensure_str(summary_a_data.get("weaknesses", ""))
            paper_a.future_work = ensure_str(summary_a_data.get("future_work", ""))
            paper_a.summary_status = "done"
            await db.commit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to generate summary for Paper A: {str(e)}")

    # If Paper B summary doesn't exist, generate it first
    if not paper_b.summary or paper_b.summary_status != "done":
        if not paper_b.extracted_text:
            raise HTTPException(status_code=400, detail=f"Paper '{paper_b.title}' text is not extracted")
        try:
            summary_b_data = await generate_summary(paper_b.extracted_text, mode=request.mode)
            paper_b.summary = ensure_str(summary_b_data.get("summary", ""))
            paper_b.research_aim = ensure_str(summary_b_data.get("research_aim", ""))
            paper_b.methodology = ensure_str(summary_b_data.get("methodology", ""))
            paper_b.key_findings = ensure_str(summary_b_data.get("key_findings", ""))
            paper_b.limitations = ensure_str(summary_b_data.get("limitations", ""))
            paper_b.strengths = ensure_str(summary_b_data.get("strengths", ""))
            paper_b.weaknesses = ensure_str(summary_b_data.get("weaknesses", ""))
            paper_b.future_work = ensure_str(summary_b_data.get("future_work", ""))
            paper_b.summary_status = "done"
            await db.commit()
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Failed to generate summary for Paper B: {str(e)}")

    # Construct the summary dicts to send to comparison prompt
    summary_a = {
        "summary": paper_a.summary,
        "research_aim": paper_a.research_aim,
        "methodology": paper_a.methodology,
        "key_findings": paper_a.key_findings,
        "limitations": paper_a.limitations,
        "strengths": paper_a.strengths,
        "weaknesses": paper_a.weaknesses,
        "future_work": paper_a.future_work
    }
    summary_b = {
        "summary": paper_b.summary,
        "research_aim": paper_b.research_aim,
        "methodology": paper_b.methodology,
        "key_findings": paper_b.key_findings,
        "limitations": paper_b.limitations,
        "strengths": paper_b.strengths,
        "weaknesses": paper_b.weaknesses,
        "future_work": paper_b.future_work
    }

    # Generate comparison using our AI service
    try:
        api_key = request.api_keys.get(request.mode, "")
        comparison_res = await generate_comparison(
            title_a=paper_a.title, summary_a=summary_a,
            title_b=paper_b.title, summary_b=summary_b,
            mode=request.mode, api_key=api_key
        )
        return comparison_res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to compare papers: {str(e)}")

@router.post("/")
async def save_comparison(
    request: ComparisonSaveRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    try:
        comparison_data_str = json.dumps(request.comparison_data)
        comp = PaperComparison(
            title=request.title,
            paper_a_id=request.paper_a_id,
            paper_b_id=request.paper_b_id,
            comparison_data=comparison_data_str,
            user_id=user_id
        )
        db.add(comp)
        await db.commit()
        await db.refresh(comp)
        return {
            "id": comp.id,
            "title": comp.title,
            "paper_a_id": comp.paper_a_id,
            "paper_b_id": comp.paper_b_id,
            "comparison_data": request.comparison_data,
            "created_at": comp.created_at
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save comparison: {str(e)}")

@router.get("/")
async def get_comparisons(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    try:
        res = await db.execute(select(PaperComparison).where(PaperComparison.user_id == user_id).order_by(PaperComparison.created_at.desc()))
        comparisons = res.scalars().all()
        
        # Load related papers to include titles in listings
        output = []
        for c in comparisons:
            res_a = await db.execute(select(ResearchPaper).where(ResearchPaper.id == c.paper_a_id, ResearchPaper.user_id == user_id))
            paper_a = res_a.scalar_one_or_none()
            
            res_b = await db.execute(select(ResearchPaper).where(ResearchPaper.id == c.paper_b_id, ResearchPaper.user_id == user_id))
            paper_b = res_b.scalar_one_or_none()
            
            output.append({
                "id": c.id,
                "title": c.title,
                "paper_a_title": paper_a.title if paper_a else "Deleted Paper",
                "paper_b_title": paper_b.title if paper_b else "Deleted Paper",
                "created_at": c.created_at
            })
        return output
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}")
async def get_comparison_detail(
    id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    res = await db.execute(select(PaperComparison).where(PaperComparison.id == id, PaperComparison.user_id == user_id))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Comparison not found")

    res_a = await db.execute(select(ResearchPaper).where(ResearchPaper.id == c.paper_a_id, ResearchPaper.user_id == user_id))
    paper_a = res_a.scalar_one_or_none()
    
    res_b = await db.execute(select(ResearchPaper).where(ResearchPaper.id == c.paper_b_id, ResearchPaper.user_id == user_id))
    paper_b = res_b.scalar_one_or_none()

    try:
        data = json.loads(c.comparison_data)
    except Exception:
        data = {}

    return {
        "id": c.id,
        "title": c.title,
        "paper_a_id": c.paper_a_id,
        "paper_b_id": c.paper_b_id,
        "paper_a_title": paper_a.title if paper_a else "Deleted Paper",
        "paper_b_title": paper_b.title if paper_b else "Deleted Paper",
        "comparison_data": data,
        "created_at": c.created_at
    }

@router.delete("/{id}")
async def delete_comparison(
    id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    res = await db.execute(select(PaperComparison).where(PaperComparison.id == id, PaperComparison.user_id == user_id))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Comparison not found")
    
    await db.delete(c)
    await db.commit()
    return {"status": "success"}

@router.put("/{id}/rename")
async def rename_comparison(
    id: str,
    request: ComparisonRenameRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    res = await db.execute(select(PaperComparison).where(PaperComparison.id == id, PaperComparison.user_id == user_id))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Comparison not found")
    
    c.title = request.title
    await db.commit()
    return {"status": "success", "title": c.title}
