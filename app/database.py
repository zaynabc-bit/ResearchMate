from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./researchmate.db")

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        from app.models.paper import ResearchPaper  # noqa
        from app.models.folder import Folder  # noqa
        from app.models.chunk import PaperChunk  # noqa
        from app.models.comparison import PaperComparison  # noqa
        await conn.run_sync(Base.metadata.create_all)
        
        # Add custom_header column if it doesn't exist
        try:
            from sqlalchemy import text
            await conn.execute(text("ALTER TABLE papers ADD COLUMN custom_header TEXT"))
        except Exception:
            pass  # Already exists
