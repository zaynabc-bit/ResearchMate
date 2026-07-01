import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
from app.database import get_db
from app.models.paper import ResearchPaper
from app.services.ai_service import (
    generate_summary, chat_with_paper, check_ollama_available,
    get_available_models, FAST_MODEL, SMART_MODEL,
)
from app.services.embedding_service import (
    build_paper_chunks, has_chunks, check_embed_available,
)
from app.models.chat import ChatMessage as DBChatMessage

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []
    mode: Optional[str] = "fast"   # e.g., "fast", "smart", "vision", "openai", "gemini", "deepseek"
    provider: Optional[str] = "local" # "local" or "cloud"
    api_keys: Optional[dict] = {}


class SummariseRequest(BaseModel):
    mode: Optional[str] = "fast"


# ── Status ────────────────────────────────────────────────

@router.get("/status")
async def ai_status():
    """Return AI provider availability and model info."""
    import os
    openai_key = os.getenv("OPENAI_API_KEY", "")
    ollama_ok = await check_ollama_available()
    embed_ok = await check_embed_available()
    models = await get_available_models() if ollama_ok else []

    fast_available = any(FAST_MODEL in m for m in models)
    smart_available = any(SMART_MODEL in m for m in models)

    active_provider = (
        "openai" if (openai_key and openai_key.strip())
        else "ollama" if ollama_ok
        else "none"
    )

    return {
        "ollama_available": ollama_ok,
        "openai_configured": bool(openai_key and openai_key.strip()),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "deepseek_configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "active_provider": active_provider,
        "embed_available": embed_ok,
        "fast_model": FAST_MODEL,
        "smart_model": SMART_MODEL,
        "fast_available": fast_available,
        "smart_available": smart_available,
        "available_models": models,
    }


# ── Summarise ─────────────────────────────────────────────

@router.post("/summarise/{paper_id}")
async def summarise_paper(
    paper_id: str,
    request: SummariseRequest = SummariseRequest(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.extracted_text:
        raise HTTPException(status_code=400, detail="No text extracted from this paper")

    ollama_ok = await check_ollama_available()
    import os
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key and not ollama_ok:
        raise HTTPException(
            status_code=503,
            detail="No AI available. Start Ollama: run 'ollama serve' in a terminal."
        )

    paper.summary_status = "generating"
    await db.commit()

    try:
        mode = request.mode or "fast"

        # Build embeddings in background while summarising (lazy init)
        embed_ok = await check_embed_available()
        if embed_ok and not await has_chunks(paper_id, db):
            print(f"[Embed] Building chunks for paper {paper_id} during summarise...")
            await build_paper_chunks(paper_id, paper.extracted_text, db)

        summary_data = await generate_summary(paper.extracted_text, mode)

        paper.summary        = summary_data.get("summary")
        paper.research_aim   = summary_data.get("research_aim")
        paper.methodology    = summary_data.get("methodology")
        paper.key_findings   = summary_data.get("key_findings")
        paper.limitations    = summary_data.get("limitations")
        paper.strengths      = summary_data.get("strengths")
        paper.weaknesses     = summary_data.get("weaknesses")
        paper.future_work    = summary_data.get("future_work")
        keywords             = summary_data.get("keywords", [])
        paper.keywords       = json.dumps(keywords) if keywords else None
        paper.summary_status = "done"

        await db.commit()
        await db.refresh(paper)
        return paper

    except HTTPException:
        raise
    except Exception as e:
        paper.summary_status = "error"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")


# ── Chat ──────────────────────────────────────────────────

@router.get("/chat/global/history")
async def get_global_chat_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBChatMessage).where(DBChatMessage.paper_id == None).order_by(DBChatMessage.created_at.asc()))
    messages = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]

@router.delete("/chat/global/history")
async def clear_global_chat_history(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBChatMessage).where(DBChatMessage.paper_id == None))
    for msg in result.scalars().all():
        await db.delete(msg)
    await db.commit()
    return {"message": "Global chat history cleared"}

@router.get("/chat/{paper_id}/history")
async def get_paper_chat_history(paper_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBChatMessage).where(DBChatMessage.paper_id == paper_id).order_by(DBChatMessage.created_at.asc()))
    messages = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]

@router.delete("/chat/{paper_id}/history")
async def clear_paper_chat_history(paper_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBChatMessage).where(DBChatMessage.paper_id == paper_id))
    for msg in result.scalars().all():
        await db.delete(msg)
    await db.commit()
    return {"message": "Paper chat history cleared"}

@router.post("/chat/global")
async def global_chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Chat with all papers globally (library RAG)."""
    ollama_ok = await check_ollama_available()
    import os
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key and not ollama_ok:
        raise HTTPException(
            status_code=503,
            detail="No AI available. Start Ollama: run 'ollama serve' in a terminal."
        )

    history = [{"role": m.role, "content": m.content} for m in request.history]
    mode = request.mode or "fast"

    # Save user message to DB
    user_msg = DBChatMessage(paper_id=None, role="user", content=request.message)
    db.add(user_msg)
    await db.commit()

    async def stream_response():
        try:
            # 0. On-the-fly auto-indexing for any papers without chunks
            from app.models.paper import ResearchPaper
            from app.services.embedding_service import has_chunks, build_paper_chunks, check_embed_available
            
            embed_ok = await check_embed_available()
            if embed_ok:
                result = await db.execute(select(ResearchPaper))
                all_papers = result.scalars().all()
                for p in all_papers:
                    if p.extracted_text and not await has_chunks(p.id, db):
                        print(f"[Global RAG] Auto-indexing paper {p.id} on query...")
                        await build_paper_chunks(p.id, p.extracted_text, db)

            # 1. Retrieve global relevant chunks
            from app.services.embedding_service import retrieve_global_relevant_chunks
            relevant = await retrieve_global_relevant_chunks(request.message, db)
            
            if not relevant:
                # Fallback: check if we have any papers at all
                from sqlalchemy import func
                from app.models.paper import ResearchPaper
                paper_count_res = await db.execute(select(func.count(ResearchPaper.id)))
                paper_count = paper_count_res.scalar()
                
                if paper_count == 0:
                    msg = json.dumps({'content': 'Your library is empty. Please upload some PDFs first!'})
                    yield f"data: {msg}\n\n"
                else:
                    msg = json.dumps({'content': "I couldn't find any relevant sections in your library. Make sure your papers are indexed (e.g. summarized or chatted with once) so their embeddings are generated."})
                    yield f"data: {msg}\n\n"
                yield "data: [DONE]\n\n"
                return

            # 2. Extract unique source papers
            sources = []
            seen = set()
            for r in relevant:
                pid = r["paper_id"]
                if pid not in seen:
                    seen.add(pid)
                    sources.append({
                        "id": pid,
                        "title": r["paper_title"]
                    })
            
            # Send source references first so frontend can display them immediately
            yield f"data: {json.dumps({'sources': sources})}\n\n"

            # 3. Format system prompt context
            context_parts = []
            for item in relevant:
                context_parts.append(
                    f"SOURCE PAPER: {item['paper_title']}\nEXCERPT:\n{item['text']}"
                )
            context = "\n\n---\n\n".join(context_parts)

            system_prompt = f"""You are ResearchMate AI — an expert academic assistant.
You help users query their entire research library.

Answer the question ONLY using the provided paper excerpts below. 
Each excerpt has a SOURCE PAPER title. 
In your response, you MUST cite the source paper title whenever you use information from it.
If the answer is not in the excerpts, say: "I couldn't find that in your library."

RELEVANT EXCERPTS:
{context}
---"""

            # 4. Stream chat response
            messages = [{"role": "system", "content": system_prompt}]
            for h in history[-8:]:
                messages.append(h)
            messages.append({"role": "user", "content": request.message})

            full_response = ""
            
            if mode in ("openai", "gemini", "deepseek"):
                api_keys = request.api_keys or {}
                api_key = api_keys.get(mode, "")
                if not api_key and mode == "openai": api_key = os.getenv("OPENAI_API_KEY", "")
                if not api_key and mode == "gemini": api_key = os.getenv("GEMINI_API_KEY", "")
                if not api_key and mode == "deepseek": api_key = os.getenv("DEEPSEEK_API_KEY", "")

                from openai import AsyncOpenAI
                if mode == "openai":
                    base_url = "https://api.openai.com/v1"
                    model_name = "gpt-4o-mini"
                elif mode == "gemini":
                    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
                    model_name = "gemini-2.5-flash"
                else: # deepseek
                    base_url = "https://api.deepseek.com"
                    model_name = "deepseek-chat"

                if not api_key:
                    yield f"data: {json.dumps({'content': f'Please provide an API key for {mode.capitalize()} in the Settings.'})}\n\n"
                else:
                    try:
                        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                        try:
                            stream = await client.chat.completions.create(
                                model=model_name, messages=messages, stream=True, temperature=0.3,
                            )
                        except Exception as e:
                            fallback_model = "gemini-3.5-flash" if model_name == "gemini-2.5-flash" else "gemini-2.5-flash"
                            print(f"[Gemini Global Fallback] Primary model {model_name} failed: {e}. Trying {fallback_model}...")
                            stream = await client.chat.completions.create(
                                model=fallback_model, messages=messages, stream=True, temperature=0.3,
                            )
                        async for chunk in stream:
                            content = chunk.choices[0].delta.content
                            if content:
                                full_response += content
                                yield f"data: {json.dumps({'content': content})}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'error': f'API Error: {str(e)}'})}\n\n"
            else:
                from app.services.ai_service import get_model_for_mode, OLLAMA_URL
                model = get_model_for_mode(mode)
                import httpx
                async with httpx.AsyncClient(timeout=180.0) as client:
                    async with client.stream(
                        "POST",
                        f"{OLLAMA_URL}/api/chat",
                        json={
                            "model": model,
                            "messages": messages,
                            "stream": True,
                            "options": {"temperature": 0.3},
                        },
                    ) as response:
                        async for line in response.aiter_lines():
                            if line:
                                try:
                                    chunk = json.loads(line)
                                    content = chunk.get("message", {}).get("content", "")
                                    if content:
                                        full_response += content
                                        yield f"data: {json.dumps({'content': content})}\n\n"
                                    if chunk.get("done"):
                                        break
                                except json.JSONDecodeError:
                                    continue
            
            if full_response:
                assistant_msg = DBChatMessage(paper_id=None, role="assistant", content=full_response)
                db.add(assistant_msg)
                await db.commit()
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@router.post("/chat/{paper_id}")
async def chat_paper(
    paper_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.extracted_text:
        raise HTTPException(status_code=400, detail="No text extracted from this paper")

    history = [{"role": m.role, "content": m.content} for m in request.history]
    mode = request.mode or "fast"

    # Save user message to DB
    user_msg = DBChatMessage(paper_id=paper_id, role="user", content=request.message)
    db.add(user_msg)
    await db.commit()

    async def stream_response():
        try:
            full_response = ""
            async for chunk in chat_with_paper(
                paper_id,
                paper.extracted_text,
                request.message,
                history,
                mode,
                request.api_keys,
                db
            ):
                full_response += chunk
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            
            if full_response:
                assistant_msg = DBChatMessage(paper_id=paper_id, role="assistant", content=full_response)
                db.add(assistant_msg)
                await db.commit()
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


# ── Index chunks (manual trigger) ─────────────────────────

@router.post("/index/{paper_id}")
async def index_paper(paper_id: str, db: AsyncSession = Depends(get_db)):
    """Manually trigger chunk + embedding generation for a paper."""
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.extracted_text:
        raise HTTPException(status_code=400, detail="No extracted text")

    embed_ok = await check_embed_available()
    if not embed_ok:
        raise HTTPException(
            status_code=503,
            detail="nomic-embed-text not available. Run: ollama pull nomic-embed-text"
        )

    n = await build_paper_chunks(paper_id, paper.extracted_text, db)
    return {"message": f"Indexed {n} chunks with embeddings", "chunks": n}



