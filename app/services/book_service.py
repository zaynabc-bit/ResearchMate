import asyncio
import json
import re
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.book import Book, BookChapter, BookChunk
from app.services.embedding_service import embed_text, check_embed_available
from app.services.ai_service import ollama_generate, SMART_MODEL, FAST_MODEL

CHUNK_SIZE = 500

def split_into_chapters(text: str) -> list:
    """Heuristic chapter detection."""
    # Look for "Chapter 1", "CHAPTER I", etc.
    pattern = r'(?i)\n(?:chapter|part|section)\s+[a-z0-9]+.*?\n'
    splits = re.split(pattern, text)
    matches = re.findall(pattern, text)
    
    chapters = []
    # If no chapters found, treat the whole book as one chapter
    if not matches:
        chapters.append({"title": "Chapter 1", "content": text.strip()})
        return chapters
        
    # The first split might be preface/intro before chapter 1
    if splits[0].strip():
        chapters.append({"title": "Introduction", "content": splits[0].strip()})
        
    for i, match in enumerate(matches):
        content = splits[i+1].strip() if i+1 < len(splits) else ""
        title = match.strip()
        chapters.append({"title": title, "content": content})
        
    return chapters

def chunk_text(text: str, words_per_chunk: int = CHUNK_SIZE) -> list:
    words = text.split()
    chunks = []
    for i in range(0, len(words), words_per_chunk):
        chunks.append(" ".join(words[i:i + words_per_chunk]))
    return chunks

async def process_book_background(book_id: str, text: str, db: AsyncSession):
    try:
        # 1. Update status
        await db.execute(update(Book).where(Book.id == book_id).values(processing_status="chunking", progress_percent=10))
        await db.commit()

        # 2. Split into chapters
        chapter_dicts = split_into_chapters(text)
        
        db_chapters = []
        for i, ch_data in enumerate(chapter_dicts):
            ch = BookChapter(
                book_id=book_id,
                chapter_index=i,
                title=ch_data["title"],
                text_content=ch_data["content"]
            )
            db.add(ch)
            db_chapters.append(ch)
            
        await db.commit()
        for ch in db_chapters:
            await db.refresh(ch)
            
        # 3. Chunk and Embed
        embed_ok = await check_embed_available()
        
        await db.execute(update(Book).where(Book.id == book_id).values(progress_percent=20))
        await db.commit()

        total_chapters = len(db_chapters)
        for i, ch in enumerate(db_chapters):
            chunks = chunk_text(ch.text_content)
            for j, c_text in enumerate(chunks):
                emb_json = None
                if embed_ok:
                    try:
                        vec = await embed_text(c_text)
                        emb_json = json.dumps(vec)
                    except Exception:
                        pass
                
                bc = BookChunk(
                    book_id=book_id,
                    chapter_id=ch.id,
                    chunk_index=j,
                    chunk_text=c_text,
                    embedding=emb_json
                )
                db.add(bc)
                
            # Update progress based on chapters embedded
            progress = 20 + int(40 * (i / max(1, total_chapters)))
            await db.execute(update(Book).where(Book.id == book_id).values(progress_percent=progress))
            await db.commit()
            
        # 4. Summarize Chapters
        await db.execute(update(Book).where(Book.id == book_id).values(processing_status="summarizing", progress_percent=60))
        await db.commit()
        
        all_chapter_summaries = []
        for i, ch in enumerate(db_chapters):
            prompt = f"""Summarize the following book chapter. You MUST format your response exactly using these Markdown headers:

### Chapter Summary
(Provide a clear summary of the chapter here)

### Key Concepts
- (List core concepts)

### Important Quotes
- "(Extract significant quotes)"

### Definitions
- **Term**: Definition

### Key Takeaways
- (List actionable or main takeaways)

Chapter Text:
{ch.text_content[:8000]}"""
            summary = await ollama_generate(prompt, FAST_MODEL)
            
            ch.summary = summary.strip() if summary else "Summary failed."
            all_chapter_summaries.append(ch.summary)
            
            progress = 60 + int(30 * (i / max(1, total_chapters)))
            await db.execute(update(Book).where(Book.id == book_id).values(progress_percent=progress))
            await db.commit()
            
        # 5. Summarize Book
        await db.execute(update(Book).where(Book.id == book_id).values(progress_percent=90))
        await db.commit()
        
        combined_ch_summaries = "\n\n".join(all_chapter_summaries)[:12000]
        exec_prompt = f"""Based on the following chapter summaries, generate a comprehensive overview for the entire book. You MUST format your response exactly using these Markdown headers:

### Executive Summary
(Provide a high-level summary of the entire book)

### Key Themes
- (List overarching themes)

### Key Concepts
- (List the most important concepts across the book)

### Overall Takeaways
- (List the ultimate conclusions or lessons)

Summaries:
{combined_ch_summaries}"""
        exec_summary = await ollama_generate(exec_prompt, SMART_MODEL)
        
        await db.execute(update(Book).where(Book.id == book_id).values(
            overall_summary=exec_summary.strip() if exec_summary else "Failed to generate book summary.",
            processing_status="done",
            progress_percent=100
        ))
        await db.commit()
        
        print(f"✅ Book {book_id} processing complete.")

    except Exception as e:
        print(f"❌ Error processing book {book_id}: {e}")
        await db.execute(update(Book).where(Book.id == book_id).values(processing_status="error"))
        await db.commit()
