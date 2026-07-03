"""
AI Service — ResearchMate

Models:
  Fast Mode  → llama3.2:3b  (quick summaries, snappy Q&A)
  Smart Mode → qwen2.5:3b   (better reasoning, deeper analysis)

Features:
  - Hierarchical summarisation: chunk → chunk summaries → final summary
  - RAG-based chat: nomic-embed-text retrieval → focused context injection
  - OpenAI fallback when API key is set
"""

import httpx
import json
import os
import re
import base64
from dotenv import load_dotenv
from typing import AsyncGenerator, List

load_dotenv()

# ── Model config ──────────────────────────────────────────
OLLAMA_URL       = os.getenv("OLLAMA_URL", "http://localhost:11434")
FAST_MODEL       = os.getenv("FAST_MODEL",  "llama3.2:3b")
SMART_MODEL      = os.getenv("SMART_MODEL", "qwen2.5:3b")
VISION_MODEL     = os.getenv("VISION_MODEL", "moondream:latest")
VISION_PRO_MODEL = os.getenv("VISION_PRO_MODEL", "llava:7b")
EMBED_MODEL      = "nomic-embed-text"

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Chunk sizes for summarisation (chars, ~3× the token count)
SUMMARISE_CHUNK = 3000   # each chunk sent for chunk-level summary
MAX_DIRECT      = 4000   # if text is shorter than this, skip chunking


# ── Prompts ───────────────────────────────────────────────

CHUNK_SUMMARY_PROMPT = """You are an academic research assistant.
Summarise the following excerpt from a research paper in 3-5 clear sentences.
Focus on: key claims, findings, and methods mentioned.
Be concise and factual. Do not invent information.

EXCERPT:
{chunk}

SUMMARY:"""

FINAL_SUMMARY_PROMPT = """You are an expert academic research assistant helping university students.

Based on the following section summaries of a research paper, produce a complete structured analysis.
Return ONLY valid JSON with exactly these fields:

{{
  "summary": "A clear 3-4 sentence plain English overview of the whole paper",
  "research_aim": "The main research question or aim in 1-2 sentences",
  "methodology": "How the research was conducted — methods, data, approach in 2-3 sentences",
  "key_findings": "The most important findings as 3-5 bullet points (use • for bullets)",
  "limitations": "Main limitations of the study in 1-2 sentences",
  "strengths": "Key strengths of the paper in 1-2 sentences",
  "weaknesses": "Notable weaknesses in 1-2 sentences",
  "future_work": "Suggested future research in 1 sentence",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
}}

Rules:
- Write simply for undergraduate students
- Do NOT invent information not in the summaries
- Return ONLY valid JSON, no extra text

SECTION SUMMARIES:
{combined_summaries}"""

DIRECT_SUMMARY_PROMPT = """You are an expert academic research assistant helping university students.

Analyse this research paper and return ONLY valid JSON with exactly these fields:

{{
  "summary": "A clear 3-4 sentence plain English overview",
  "research_aim": "The main research question or aim in 1-2 sentences",
  "methodology": "How the research was conducted in 2-3 sentences",
  "key_findings": "The most important findings as 3-5 bullet points (use • for bullets)",
  "limitations": "Main limitations in 1-2 sentences",
  "strengths": "Key strengths in 1-2 sentences",
  "weaknesses": "Notable weaknesses in 1-2 sentences",
  "future_work": "Suggested future research in 1 sentence",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
}}

Rules:
- Write simply for undergraduate students
- Do NOT invent information
- Return ONLY valid JSON, no extra text

PAPER TEXT:
{text}"""

RAG_CHAT_SYSTEM = """You are ResearchMate AI — an expert academic research assistant.
You help university students understand research papers.

You MUST only answer using the provided paper excerpts below.
If the answer is not in the excerpts, say: "I couldn't find that in this paper."
Be clear, helpful, and accessible to students.

RELEVANT EXCERPTS FROM THE PAPER:
{context}
---"""

FALLBACK_CHAT_SYSTEM = """You are ResearchMate AI — an expert academic research assistant.
You help university students understand research papers.
Answer ONLY using the paper content provided. Do not use outside knowledge.
Be clear, helpful, and accessible to students.

PAPER CONTENT (excerpt):
{context}
---"""


# ── Availability checks ───────────────────────────────────

async def check_ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def get_available_models() -> List[str]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def get_model_for_mode(mode: str) -> str:
    """Return the Ollama model name for the given mode."""
    if mode == "phi3":
        return VISION_MODEL  # reusing slot — actually phi3:latest
    if mode == "vision":
        return VISION_MODEL
    if mode == "vision_pro":
        return VISION_PRO_MODEL
    return SMART_MODEL if mode == "smart" else FAST_MODEL


def get_base64_images_for_slide(paper_id: str, slide_num: int) -> list:
    """Find images for a given slide and return them as base64 strings."""
    upload_dir = os.getenv("UPLOAD_DIR", "uploads")
    slides_dir = os.path.join(upload_dir, "slides", paper_id)
    if not os.path.isdir(slides_dir):
        return []

    images_b64 = []
    for fname in sorted(os.listdir(slides_dir)):
        m = re.match(rf"slide_{slide_num:03d}_img_", fname)
        if m:
            img_path = os.path.join(slides_dir, fname)
            ext = fname.split('.')[-1].lower()
            mime_type = "image/png" if ext == "png" else "image/jpeg"
            try:
                with open(img_path, "rb") as f:
                    b64_str = base64.b64encode(f.read()).decode("utf-8")
                    images_b64.append({"b64": b64_str, "mime": mime_type})
            except Exception as e:
                print(f"[Vision] Error encoding image {img_path}: {e}")
    return images_b64


# ── Core Ollama call ──────────────────────────────────────

async def ollama_generate(prompt: str, model: str, json_mode: bool = False) -> str:
    """Non-streaming Ollama generate call. Returns raw response text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 1200,
            "num_ctx": 8192,
            "num_gpu": 99,
            "num_thread": 4,
            "num_batch": 512,
        },
    }
    if json_mode:
        payload["format"] = "json"

    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
        r.raise_for_status()
        return r.json().get("response", "")


# ── Summarisation ─────────────────────────────────────────

def split_into_chunks(text: str, chunk_size: int = SUMMARISE_CHUNK) -> List[str]:
    """Split text into chunks for hierarchical summarisation."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        # Try sentence boundary
        boundary = text.rfind('. ', start + chunk_size // 2, end)
        if boundary != -1:
            end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


async def summarise_chunk(chunk: str, model: str) -> str:
    """Summarise a single chunk — used in hierarchical summarisation."""
    prompt = CHUNK_SUMMARY_PROMPT.format(chunk=chunk)
    return await ollama_generate(prompt, model)


async def generate_summary_ollama(text: str, mode: str = "fast") -> dict:
    """
    Hierarchical summarisation strategy:
      Short paper  → direct summarisation
      Long paper   → chunk → summarise each chunk → summarise chunk summaries → final JSON
    """
    model = get_model_for_mode(mode)

    if len(text) <= MAX_DIRECT:
        prompt = DIRECT_SUMMARY_PROMPT.format(text=text[:MAX_DIRECT])
        raw = await ollama_generate(prompt, model, json_mode=True)
    else:
        chunks = split_into_chunks(text, SUMMARISE_CHUNK)
        print(f"[AI] Hierarchical summarise: {len(chunks)} chunks with {model}")

        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            print(f"[AI] Summarising chunk {i+1}/{len(chunks)}...")
            summary = await summarise_chunk(chunk, model)
            chunk_summaries.append(f"Section {i+1}:\n{summary.strip()}")

        combined = "\n\n".join(chunk_summaries)
        if len(combined) > 5000:
            combined = combined[:5000]

        prompt = FINAL_SUMMARY_PROMPT.format(combined_summaries=combined)
        raw = await ollama_generate(prompt, model, json_mode=True)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except Exception:
                pass
        return {
            "summary": raw[:500] if raw else "Summary generation failed",
            "research_aim": None, "methodology": None, "key_findings": None,
            "limitations": None, "strengths": None, "weaknesses": None,
            "future_work": None, "keywords": [],
        }


async def generate_summary_openai(text: str) -> dict:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    truncated = text[:12000]
    prompt = DIRECT_SUMMARY_PROMPT.format(text=truncated)
    response = await client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return json.loads(response.choices[0].message.content)


async def generate_summary(text: str, mode: str = "fast") -> dict:
    """Entry point — use OpenAI if key set, else Ollama."""
    if OPENAI_API_KEY and OPENAI_API_KEY.strip():
        return await generate_summary_openai(text)
    return await generate_summary_ollama(text, mode)


# ── RAG Chat (Ollama) ─────────────────────────────────────

async def chat_with_paper_ollama(
    paper_id: str,
    paper_text: str,
    message: str,
    history: list,
    mode: str = "fast",
    db=None,
    model_override: str = None,
) -> AsyncGenerator[str, None]:
    """RAG-enhanced streaming chat using Ollama."""
    model = model_override or get_model_for_mode(mode)

    if db is not None:
        try:
            from app.services.embedding_service import retrieve_relevant_chunks, has_chunks, build_paper_chunks
            if not await has_chunks(paper_id, db):
                print(f"[RAG] Building chunks for paper {paper_id}...")
                await build_paper_chunks(paper_id, paper_text, db)

            relevant = await retrieve_relevant_chunks(paper_id, message, db)
            if relevant:
                context = "\n\n---\n\n".join(relevant)
                system = RAG_CHAT_SYSTEM.format(context=context)
                print(f"[RAG] Retrieved {len(relevant)} chunks for query")
            else:
                raise ValueError("No chunks retrieved")
        except Exception as e:
            print(f"[RAG] Fallback to direct context: {e}")
            context = paper_text[:3000]
            system = FALLBACK_CHAT_SYSTEM.format(context=context)
    else:
        context = paper_text[:3000]
        system = FALLBACK_CHAT_SYSTEM.format(context=context)

    messages = [{"role": "system", "content": system}]
    for h in history[-8:]:
        messages.append(h)

    user_msg = {"role": "user", "content": message}
    if mode in ("vision", "vision_pro"):
        slide_match = re.search(r'(?i)\bslides?\s*(\d+)', message)
        if slide_match:
            slide_num = int(slide_match.group(1))
            print(f"[Vision] User asking about slide {slide_num}. Extracting images...")
            b64_imgs = get_base64_images_for_slide(paper_id, slide_num)
            if b64_imgs:
                user_msg["images"] = b64_imgs
                print(f"[Vision] Injected {len(b64_imgs)} image(s) into prompt.")
                messages[0]["content"] += "\n\n[System Note: The user has attached an image of the slide. Analyze it carefully.]"
            else:
                print(f"[Vision] No images found for slide {slide_num}.")

    messages.append(user_msg)

    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": 0.3,
                    "num_ctx": 8192,       # M2 has plenty of unified memory
                    "num_gpu": 99,         # Use all Metal GPU layers on Apple Silicon
                    "num_thread": 4,       # M2 base: 4 performance cores
                    "num_batch": 512,      # Larger batch = faster prompt processing
                },
            },
        ) as response:
            async for line in response.aiter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue


# ── Cloud Chat (Gemini / OpenAI / DeepSeek) ───────────────

async def chat_with_paper_cloud(
    paper_id: str,
    paper_text: str,
    message: str,
    history: list,
    provider: str,
    api_key: str,
    mode: str,
) -> AsyncGenerator[str, None]:
    """Route to Gemini native REST API or OpenAI-compatible client."""
    if not api_key:
        yield f"[No API key provided for {provider.capitalize()}. Please add one in Settings.]"
        return

    truncated = paper_text[:15000] if paper_text else ""  # Gemini has large context
    system = FALLBACK_CHAT_SYSTEM.format(context=truncated)

    # ── GEMINI NATIVE REST API ────────────────────────────────────────────
    if provider == "gemini":
        contents = []
        for h in history[-8:]:
            role = "model" if h["role"] in ("assistant", "system") else "user"
            contents.append({"role": role, "parts": [{"text": h["content"]}]})

        user_parts = [{"text": message}]

        # Vision: inject slide images if user references a slide number
        slide_match = re.search(r'(?i)\bslides?\s*(\d+)', message)
        if slide_match:
            slide_num = int(slide_match.group(1))
            imgs = get_base64_images_for_slide(paper_id, slide_num)
            for img_data in imgs:
                user_parts.append({
                    "inline_data": {"mime_type": img_data["mime"], "data": img_data["b64"]}
                })
            if imgs:
                print(f"[Gemini Vision] Injected {len(imgs)} image(s) for slide {slide_num}")
        elif re.search(r'(?i)\b(image|chart|figure|diagram|graph|table|visual|picture|photo)\b', message):
            # User asked about a visual element — inject first available slide image
            upload_dir = os.getenv("UPLOAD_DIR", "uploads")
            slides_dir = os.path.join(upload_dir, "slides", paper_id)
            if os.path.isdir(slides_dir):
                for fname in sorted(os.listdir(slides_dir))[:3]:  # first 3 images max
                    ext = fname.split('.')[-1].lower()
                    mime_type = "image/png" if ext == "png" else "image/jpeg"
                    try:
                        with open(os.path.join(slides_dir, fname), "rb") as f:
                            b64 = base64.b64encode(f.read()).decode()
                            user_parts.append({"inline_data": {"mime_type": mime_type, "data": b64}})
                    except Exception:
                        pass
                if len(user_parts) > 1:
                    print(f"[Gemini Vision] Injected {len(user_parts)-1} figure image(s) for visual query")

        contents.append({"role": "user", "parts": user_parts})
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.3},
        }

        models_to_try = ["gemini-2.5-flash", "gemini-3.5-flash"]
        success = False
        
        for model in models_to_try:
            gemini_url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:streamGenerateContent?alt=sse&key={api_key}"
            )
            print(f"[Gemini] Requesting... model={model} key={api_key[:12]}")
            try:
                async with httpx.AsyncClient() as http_client:
                    async with http_client.stream("POST", gemini_url, json=payload, timeout=60.0) as response:
                        print(f"[Gemini] HTTP {response.status_code}")
                        if response.status_code != 200:
                            err = await response.aread()
                            print(f"[Gemini] Model {model} returned HTTP {response.status_code}: {err.decode()[:150]}")
                            continue
                        
                        success = True
                        count = 0
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line or not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk_json = json.loads(data_str)
                                candidates = chunk_json.get("candidates", [])
                                if candidates:
                                    for part in candidates[0].get("content", {}).get("parts", []):
                                        text = part.get("text", "")
                                        if text:
                                            count += 1
                                            yield text
                            except Exception:
                                pass
                        print(f"[Gemini] Stream done using {model}. {count} chunks.")
                        break
            except Exception as e:
                print(f"[Gemini] Error with model {model}: {e}")
                continue
                
        if not success:
            yield "[Gemini Error: All attempted models failed. Please try again later.]"
        return

    # ── OPENAI / DEEPSEEK ─────────────────────────────────────────────────
    from openai import AsyncOpenAI

    if provider == "openai":
        base_url = "https://api.openai.com/v1"
        model_name = "gpt-4o-mini"
    elif provider == "deepseek":
        base_url = "https://api.deepseek.com"
        model_name = "deepseek-chat"
    else:
        yield f"[Unknown provider: {provider}]"
        return

    messages = [{"role": "system", "content": system}]
    for h in history[-8:]:
        messages.append(h)

    user_msg: dict = {"role": "user", "content": message}
    if provider == "openai":
        slide_match = re.search(r'(?i)\bslides?\s*(\d+)', message)
        if slide_match:
            slide_num = int(slide_match.group(1))
            img_data_list = get_base64_images_for_slide(paper_id, slide_num)
            if img_data_list:
                content_list: list = [{"type": "text", "text": message}]
                for img_data in img_data_list:
                    content_list.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{img_data['mime']};base64,{img_data['b64']}"}
                    })
                user_msg["content"] = content_list

    messages.append(user_msg)

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    stream = await client.chat.completions.create(
        model=model_name, messages=messages, stream=True, temperature=0.3,
    )
    async for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            yield content


# ── Entry Point ───────────────────────────────────────────

async def chat_with_paper(
    paper_id: str,
    paper_text: str,
    message: str,
    history: list,
    mode: str = "fast",
    api_keys: dict = None,
    db=None,
) -> AsyncGenerator[str, None]:
    """Route to cloud provider or local Ollama."""
    api_keys = api_keys or {}

    if mode in ("openai", "gemini", "deepseek"):
        api_key = api_keys.get(mode, "")
        # Fallback to backend .env keys
        if not api_key and mode == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key and mode == "gemini":
            api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key and mode == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY", "")

        async for chunk in chat_with_paper_cloud(paper_id, paper_text, message, history, provider=mode, api_key=api_key, mode=mode):
            yield chunk
    else:
        # Local Ollama — phi3, fast, smart
        ollama_model = {
            "phi3": "phi3:latest",
            "fast": FAST_MODEL,
            "smart": SMART_MODEL,
        }.get(mode, FAST_MODEL)
        async for chunk in chat_with_paper_ollama(paper_id, paper_text, message, history, mode, db, model_override=ollama_model):
            yield chunk


# ── Comparison Generation ─────────────────────────────────

COMPARISON_PROMPT = """You are an expert academic research assistant comparing two academic papers.
Below are the structured summaries of the two papers:

Paper A Title: {title_a}
Summary A:
{summary_a}

Paper B Title: {title_b}
Summary B:
{summary_b}

Please provide an intelligent, critical, and synthesised comparison of these two papers.
You MUST respond with a single JSON object containing exactly the following keys:
1. "title": A short academic comparison title (e.g. "Comparative Analysis: [Topic] vs [Topic]")
2. "table": An object where keys are categories ("Aim", "Methodology", "Sample Size", "Population", "Key Findings", "Strengths", "Weaknesses", "Limitations", "Ethical Considerations") and values are objects: {{"paper_a": "summary of category for paper A", "paper_b": "summary of category for paper B"}}
3. "narrative": A natural-language academic discussion (2-3 paragraphs) explaining the relationship, similarities, and differences between the papers.
4. "confidence": An 'Evidence Confidence' analysis comparing the quality of evidence. Who provides stronger evidence and why (e.g., sample size, design, recency)?
5. "agreement": An array of objects: [{{"topic": "Category Name", "status": "agreement" | "partial" | "contradiction", "explanation": "Detail explaining this status"}}]

Ensure your output is valid JSON."""

async def generate_comparison(
    title_a: str, summary_a: dict,
    title_b: str, summary_b: dict,
    mode: str = "fast",
    api_key: str = ""
) -> dict:
    """Route comparison request to cloud provider or local Ollama."""
    import os
    formatted_summary_a = json.dumps(summary_a, indent=2)
    formatted_summary_b = json.dumps(summary_b, indent=2)
    prompt = COMPARISON_PROMPT.format(
        title_a=title_a, summary_a=formatted_summary_a,
        title_b=title_b, summary_b=formatted_summary_b
    )

    if mode in ("openai", "gemini", "deepseek"):
        api_key = api_key or ""
        if not api_key and mode == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key and mode == "gemini":
            api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key and mode == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY", "")

        if mode == "gemini":
            contents = [{"role": "user", "parts": [{"text": prompt}]}]
            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json"
                },
            }
            models_to_try = ["gemini-2.5-flash", "gemini-3.5-flash"]
            raw = None
            for model in models_to_try:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                try:
                    async with httpx.AsyncClient() as client:
                        r = await client.post(gemini_url, json=payload, timeout=60.0)
                        if r.status_code == 200:
                            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                            break
                except Exception as e:
                    print(f"[Gemini Compare] Error with {model}: {e}")
            if not raw:
                raise Exception("All attempted Gemini models failed during comparison generation.")
        
        else:
            # OpenAI or DeepSeek
            from openai import AsyncOpenAI
            if mode == "openai":
                base_url = "https://api.openai.com/v1"
                model_name = "gpt-4o-mini"
            else:
                base_url = "https://api.deepseek.com"
                model_name = "deepseek-chat"

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw = response.choices[0].message.content
    
    else:
        # Local Ollama
        ollama_model = {
            "phi3": "phi3:latest",
            "fast": FAST_MODEL,
            "smart": SMART_MODEL,
        }.get(mode, FAST_MODEL)

        raw = await ollama_generate(prompt, ollama_model, json_mode=True)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end])
            except Exception:
                pass
        raise Exception(f"Failed to parse LLM comparison output: {raw[:300]}")
# ── Rewrite Studio ────────────────────────────────────────

async def rewrite_text(original_text: str, mode: str, tone_example: str = None) -> str:
    """Rewrite text using AI based on the specified mode."""
    mode_prompts = {
        "natural": "Rewrite the following text to sound more natural and fluent.",
        "academic": "Rewrite the following text in a formal academic tone suitable for university-level research.",
        "professional": "Rewrite the following text in a clear, professional business style.",
        "friendly": "Rewrite the following text in a warm, friendly, and conversational tone.",
        "simple": "Rewrite the following text in Simple English so it is extremely easy to understand.",
        "concise": "Rewrite the following text to be concise. Remove unnecessary words and fluff while keeping the core message.",
        "expand": "Expand on the ideas in the following text, providing more detail and elaboration without inventing new facts.",
        "grammar": "Correct all grammar, spelling, and punctuation errors in the following text, and improve its clarity.",
        "british": "Rewrite the following text using British English spelling (e.g., 'ise' instead of 'ize', 'colour' instead of 'color') and phrasing.",
        "american": "Rewrite the following text using American English spelling and phrasing.",
    }
    
    instruction = mode_prompts.get(mode, mode_prompts["natural"])
    if mode == "tone" and tone_example:
        instruction = f"Rewrite the following text to match the tone and style of this example:\n[EXAMPLE]\n{tone_example}\n[END EXAMPLE]"
        
    system_prompt = f"""You are an expert writing assistant and copyeditor.
Your task is to rewrite the user's text according to the following instruction:
{instruction}

CRITICAL RULES:
- Never invent facts.
- Never fabricate references.
- Never change the intended meaning of the original text.
- Never add unsupported claims.
- Preserve the original formatting where possible.
- Output ONLY the rewritten text, nothing else. Do not add introductory or concluding remarks."""

    payload = {
        "model": SMART_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": original_text}
        ],
        "stream": False,
        "options": {"temperature": 0.4}
    }
    
    url = f"{OLLAMA_URL}/api/chat"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()
    except Exception as e:
        print(f"Ollama rewrite error: {e}")
        raise

async def generate_synthesis(combined_text: str, style: str, custom_prompt: str) -> str:
    system_prompt = f"""You are an expert academic writer and researcher.
Your task is to synthesize the provided source materials into a single, cohesive, well-structured, and highly technical document.

FORMATTING REQUIRED: {style}
You must strictly adhere to the {style} formatting style for both structure and citations.

INSTRUCTIONS:
{custom_prompt if custom_prompt else "Synthesize the core findings, methodologies, and discussions from the sources into a comprehensive literature review."}

RULES:
- Start the document with a `# ` header containing an intelligent, synthetic title that accurately reflects the synthesized content.
- Do NOT invent facts.
- Use only the provided sources. If you cite something, it must be from the text below.
- Do NOT use placeholder references like "Reference for X". You MUST use the provided metadata (Authors, Year, Journal) to generate REAL, properly formatted citations.
- Ensure smooth transitions and logical flow.
- Format the output using markdown.
- Include a references section at the end containing all citations used in the requested style.
"""

    payload = {
        "model": SMART_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"SOURCE MATERIALS:\n\n{combined_text}"}
        ],
        "stream": False,
        "options": {"temperature": 0.4}
    }
    
    url = f"{OLLAMA_URL}/api/chat"
    try:
        async with httpx.AsyncClient() as client:
            # allow longer timeout for synthesis
            resp = await client.post(url, json=payload, timeout=180.0)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()
    except Exception as e:
        print(f"Ollama synthesis error: {e}")
        raise
