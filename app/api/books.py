import os
import json
import httpx
import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import Optional, List, Dict
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.api.auth import get_current_user_id
from app.models.book import Book, BookChapter, BookChunk, BookChatMessage
from app.services.book_service import process_book_background
from app.services.pdf_service import extract_text_from_pdf

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.get("")
async def get_books(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(select(Book).where(Book.user_id == user_id).order_by(Book.created_at.desc()))
    books = result.scalars().all()
    return books

@router.get("/{book_id}")
async def get_book_details(book_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(
        select(Book).options(selectinload(Book.chapters)).where(Book.id == book_id, Book.user_id == user_id)
    )
    book = result.scalars().first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
        
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "overall_summary": book.overall_summary,
        "processing_status": book.processing_status,
        "progress_percent": book.progress_percent,
        "chapters": [
            {
                "id": ch.id,
                "title": ch.title,
                "summary": ch.summary,
                "chapter_index": ch.chapter_index
            } for ch in book.chapters
        ]
    }

@router.get("/{book_id}/chapters/{chapter_id}")
async def get_chapter(book_id: str, chapter_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(
        select(BookChapter).where(BookChapter.id == chapter_id, BookChapter.book_id == book_id)
    )
    chapter = result.scalars().first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    return chapter

@router.post("/upload")
async def upload_book(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDFs are currently supported for Books.")
        
    title = file.filename.replace(".pdf", "")
    file_path = os.path.join(UPLOAD_DIR, f"book_{user_id}_{file.filename}")
    
    # Save file
    content = await file.read()
    async with aiofiles.open(file_path, 'wb') as out_file:
        await out_file.write(content)
        
    # Extract text
    try:
        text_content, _, _ = extract_text_from_pdf(file_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read PDF: {e}")
        
    # Create DB entry
    new_book = Book(
        user_id=user_id,
        title=title,
        file_url=f"/files/{os.path.basename(file_path)}",
        file_size=len(content),
        processing_status="pending"
    )
    db.add(new_book)
    await db.commit()
    await db.refresh(new_book)
    
    # Kick off background job
    background_tasks.add_task(process_book_background, new_book.id, text_content, db)
    
    return {"message": "Book uploaded successfully. Processing in background.", "book_id": new_book.id}

@router.delete("/{book_id}")
async def delete_book(book_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(select(Book).where(Book.id == book_id, Book.user_id == user_id))
    book = result.scalars().first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
        
    await db.delete(book)
    await db.commit()
    return {"status": "ok"}

class BookChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    mode: Optional[str] = "fast"
    api_keys: Optional[Dict[str, str]] = None

@router.get("/{book_id}/chat/history")
async def get_book_chat_history(book_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(
        select(BookChatMessage).where(BookChatMessage.book_id == book_id, BookChatMessage.user_id == user_id).order_by(BookChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return [{"role": m.role, "content": m.content} for m in messages]

@router.delete("/{book_id}/chat/history")
async def clear_book_chat_history(book_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    result = await db.execute(
        select(BookChatMessage).where(BookChatMessage.book_id == book_id, BookChatMessage.user_id == user_id)
    )
    for msg in result.scalars().all():
        await db.delete(msg)
    await db.commit()
    return {"message": "Book chat history cleared"}

@router.post("/{book_id}/chat")
async def book_chat(
    book_id: str,
    request: BookChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id)
):
    from app.services.ai_service import check_ollama_available
    ollama_ok = await check_ollama_available()
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key and not ollama_ok:
        raise HTTPException(
            status_code=503,
            detail="No AI available. Start Ollama: run 'ollama serve' in a terminal."
        )

    # Save user message to DB
    user_msg = BookChatMessage(book_id=book_id, role="user", content=request.message, user_id=user_id)
    db.add(user_msg)
    await db.commit()

    async def stream_response():
        try:
            # 1. Retrieve relevant chunks
            from app.services.embedding_service import retrieve_book_chunks
            relevant_chunks = await retrieve_book_chunks(book_id, request.message, db)
            
            if not relevant_chunks:
                msg = json.dumps({'content': "I couldn't find any relevant sections in this book."})
                yield f"data: {msg}\n\n"
                yield "data: [DONE]\n\n"
                return

            context = "\n\n---\n\n".join(relevant_chunks)

            system_prompt = f"""You are ResearchMate AI — an expert academic assistant.
You are helping the user understand a specific book they have imported.

Answer the question ONLY using the provided book excerpts below.
If the answer is not in the excerpts, say: "I couldn't find that in this book." Do not hallucinate or use outside knowledge.

RELEVANT EXCERPTS:
{context}
---"""

            messages = [{"role": "system", "content": system_prompt}]
            for h in request.history[-8:]:
                messages.append(h)
            messages.append({"role": "user", "content": request.message})

            full_response = ""
            mode = request.mode or "fast"
            
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
                        stream = await client.chat.completions.create(
                            model=model_name, messages=messages, stream=True, temperature=0.3,
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
                async with httpx.AsyncClient(timeout=180.0) as client:
                    async with client.stream(
                        "POST",
                        f"{OLLAMA_URL}/api/chat",
                        json={"model": model, "messages": messages, "stream": True}
                    ) as response:
                        if response.status_code != 200:
                            yield f"data: {json.dumps({'error': f'Ollama Error: {response.status_code}'})}\n\n"
                        else:
                            async for line in response.aiter_lines():
                                if not line: continue
                                try:
                                    data = json.loads(line)
                                    msg_content = data.get("message", {}).get("content", "")
                                    if msg_content:
                                        full_response += msg_content
                                        yield f"data: {json.dumps({'content': msg_content})}\n\n"
                                except json.JSONDecodeError:
                                    pass

            # Save AI response
            if full_response.strip():
                # We need a new session here because the generator is streaming
                async for new_db in get_db():
                    ai_msg = BookChatMessage(book_id=book_id, role="assistant", content=full_response.strip(), user_id=user_id)
                    new_db.add(ai_msg)
                    await new_db.commit()
                    break

            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")
