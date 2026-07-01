import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import init_db
from app.api import papers, folders, ai, comparisons
from dotenv import load_dotenv

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    os.makedirs(os.getenv("UPLOAD_DIR", "uploads"), exist_ok=True)
    print("✅ ResearchMate started — database ready")
    yield
    # Shutdown
    print("👋 ResearchMate shutting down")


app = FastAPI(
    title="ResearchMate API",
    description="AI-powered academic research workspace",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(papers.router, prefix="/api/papers", tags=["Papers"])
app.include_router(folders.router, prefix="/api/folders", tags=["Folders"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(comparisons.router, prefix="/api/comparisons", tags=["Comparisons"])


# Serve uploaded files (including nested paths like slides/{paper_id}/{img})
@app.get("/uploads/{file_path:path}")
async def serve_upload(file_path: str):
    import mimetypes
    upload_dir = os.getenv("UPLOAD_DIR", "uploads")
    full_path = os.path.join(upload_dir, file_path)
    # Prevent directory traversal
    full_path = os.path.realpath(full_path)
    upload_dir_real = os.path.realpath(upload_dir)
    if not full_path.startswith(upload_dir_real):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Forbidden")
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    mime_type, _ = mimetypes.guess_type(full_path)
    if not mime_type:
        mime_type = "application/octet-stream"
    return FileResponse(full_path, media_type=mime_type)


# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Serve the SPA for all other routes
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/")
async def root():
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
