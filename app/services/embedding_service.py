"""
Embedding service using Ollama's nomic-embed-text.

Handles:
  - Text chunking with overlap
  - Generating embeddings per chunk via Ollama
  - Storing chunks + embeddings in SQLite
  - Cosine similarity retrieval (RAG)
"""

import json
import math
import httpx
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from app.models.chunk import PaperChunk

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"

# Chunking config — tuned for 3B model context window
CHUNK_SIZE = 800        # chars per chunk (~200 tokens)
CHUNK_OVERLAP = 150     # overlap to preserve context across boundaries
TOP_K_CHUNKS = 4        # number of chunks returned per query


# ──────────────────────────────────────────
# TEXT CHUNKING
# ──────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Split text into overlapping chunks.
    Tries to split on sentence boundaries ('. ') where possible.
    """
    if not text or len(text.strip()) == 0:
        return []

    text = text.strip()
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            # Last chunk — take whatever remains
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Try to split at a sentence boundary near the end of the chunk
        boundary = text.rfind('. ', start + chunk_size // 2, end)
        if boundary != -1:
            end = boundary + 1  # include the period

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Move forward with overlap
        start = end - overlap
        if start <= 0:
            start = end  # safety guard

    return chunks


# ──────────────────────────────────────────
# EMBEDDING GENERATION
# ──────────────────────────────────────────

async def embed_text(text: str) -> List[float]:
    """Generate a single embedding vector using nomic-embed-text via Ollama."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
        response.raise_for_status()
        data = response.json()
        return data.get("embedding", [])


async def check_embed_available() -> bool:
    """Check if nomic-embed-text is available in Ollama."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return False
            models = [m["name"] for m in r.json().get("models", [])]
            return any("nomic-embed-text" in m for m in models)
    except Exception:
        return False


# ──────────────────────────────────────────
# CHUNK + EMBED A PAPER (called once per paper)
# ──────────────────────────────────────────

async def build_paper_chunks(paper_id: str, text: str, db: AsyncSession) -> int:
    """
    Chunk paper text, generate embeddings for each chunk,
    and store in paper_chunks table. Returns number of chunks created.
    """
    # Delete old chunks for this paper (e.g. re-indexing)
    await db.execute(delete(PaperChunk).where(PaperChunk.paper_id == paper_id))
    await db.commit()

    # Prepend paper metadata (title, authors, custom header) to the text to be chunked
    from app.models.paper import ResearchPaper
    result = await db.execute(select(ResearchPaper).where(ResearchPaper.id == paper_id))
    paper = result.scalar_one_or_none()

    prefix = ""
    if paper:
        metadata_parts = []
        if paper.title:
            metadata_parts.append(f"Title: {paper.title}")
        if paper.authors:
            metadata_parts.append(f"Authors: {paper.authors}")
        if paper.custom_header:
            metadata_parts.append(f"Description/Summary: {paper.custom_header}")
        
        if metadata_parts:
            prefix = "\n".join(metadata_parts) + "\n\n"

    full_text = prefix + (text or "")
    chunks = chunk_text(full_text)
    if not chunks:
        return 0

    embed_ok = await check_embed_available()

    for idx, chunk_text_val in enumerate(chunks):
        embedding_json = None

        if embed_ok:
            try:
                vec = await embed_text(chunk_text_val)
                embedding_json = json.dumps(vec)
            except Exception as e:
                print(f"Embedding failed for chunk {idx}: {e}")

        chunk_obj = PaperChunk(
            paper_id=paper_id,
            chunk_index=idx,
            chunk_text=chunk_text_val,
            embedding=embedding_json,
        )
        db.add(chunk_obj)

    await db.commit()
    return len(chunks)


# ──────────────────────────────────────────
# COSINE SIMILARITY
# ──────────────────────────────────────────

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ──────────────────────────────────────────
# SEMANTIC RETRIEVAL (RAG)
# ──────────────────────────────────────────

async def retrieve_relevant_chunks(
    paper_id: str,
    query: str,
    db: AsyncSession,
    top_k: int = TOP_K_CHUNKS,
) -> List[str]:
    """
    Embed the query and return the top-k most semantically similar
    chunks from this paper. Falls back to first N chunks if no embeddings.
    """
    result = await db.execute(
        select(PaperChunk)
        .where(PaperChunk.paper_id == paper_id)
        .order_by(PaperChunk.chunk_index)
    )
    all_chunks = result.scalars().all()

    # Check if user is asking about a specific slide
    target_slide = None
    import re
    slide_match = re.search(r'(?i)\bslides?\s*(\d+)', query)
    if slide_match:
        target_slide = f"--- Slide {slide_match.group(1)} ---"

    query_vec = None
    try:
        query_vec = await embed_text(query)
    except Exception as e:
        print(f"[RAG] Local query embedding failed: {e}, falling back to text search.")

    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored: List[Tuple[float, str]] = []
    for chunk in all_chunks:
        score = 0.0
        
        # 1. Semantic scoring
        if query_vec and chunk.embedding:
            try:
                chunk_vec = json.loads(chunk.embedding)
                score = cosine_similarity(query_vec, chunk_vec)
            except Exception:
                pass
                
        # 2. Textual Fallback scoring
        if score == 0.0:
            chunk_text_lower = chunk.chunk_text.lower()
            overlap = sum(1 for word in query_words if word in chunk_text_lower)
            if overlap > 0:
                score = (overlap / len(query_words)) * 0.5
                
        # Boost score if this chunk contains the exact slide being asked about
        if target_slide and target_slide in chunk.chunk_text:
            score += 1.0  # Massive boost to guarantee it gets retrieved

        if score > 0.0:
            scored.append((score, chunk.chunk_text))

    # Sort by similarity descending
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # If we couldn't find anything at all (e.g. no words matched), return first k chunks as absolute fallback
    if not scored:
        return [c.chunk_text for c in all_chunks[:top_k]]

    return [text for _, text in scored[:top_k]]


async def has_chunks(paper_id: str, db: AsyncSession) -> bool:
    """Check if a paper already has chunks stored."""
    result = await db.execute(
        select(PaperChunk.id).where(PaperChunk.paper_id == paper_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def retrieve_global_relevant_chunks(
    query: str,
    db: AsyncSession,
    user_id: str,
    top_k: int = 5,
) -> list:
    """Retrieve semantically similar chunks across ALL papers in the database for a user."""
    from app.models.paper import ResearchPaper
    
    query_vec = None
    try:
        query_vec = await embed_text(query)
    except Exception as e:
        print(f"[RAG] Global query embedding failed: {e}, falling back to text search.")

    # Fetch all chunks joined with their parent paper metadata, filtered by user_id
    # We fetch chunks even if embedding is None to support the fallback
    result = await db.execute(
        select(PaperChunk, ResearchPaper.title, ResearchPaper.id)
        .join(ResearchPaper, PaperChunk.paper_id == ResearchPaper.id)
        .where(ResearchPaper.user_id == user_id)
    )
    rows = result.all()

    if not rows:
        return []

    scored = []
    query_lower = query.lower()
    query_words = set(query_lower.split())

    for chunk, title, paper_id in rows:
        score = 0.0
        
        # 1. Semantic scoring
        if query_vec and chunk.embedding:
            try:
                chunk_vec = json.loads(chunk.embedding)
                score = cosine_similarity(query_vec, chunk_vec)
            except Exception:
                pass
                
        # 2. Textual Fallback scoring (TF-style keyword overlap)
        if score == 0.0:
            chunk_text_lower = chunk.chunk_text.lower()
            overlap = sum(1 for word in query_words if word in chunk_text_lower)
            if overlap > 0:
                score = (overlap / len(query_words)) * 0.5  # Max fallback score is 0.5 (lower than high-confidence semantic matches)
                
        # 3. Boost for title matches
        if any(word in title.lower() for word in query_words):
            score += 0.2

        if score > 0.05: # Minimum threshold
            scored.append({
                "score": score,
                "text": chunk.chunk_text,
                "paper_title": title,
                "paper_id": paper_id
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
