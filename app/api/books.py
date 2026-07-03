import os
import aiofiles
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from typing import Optional
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
