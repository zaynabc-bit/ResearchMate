from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = "sqlite+aiosqlite:///./researchmate.db"

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

        # Auto-migration: add missing columns without dropping data
        migrations = [
            ("papers",       "custom_header TEXT"),
            ("papers",       "user_id TEXT DEFAULT 'local-user'"),
            ("folders",      "user_id TEXT DEFAULT 'local-user'"),
            ("paper_chunks", "user_id TEXT DEFAULT 'local-user'"),
            ("chat_messages","user_id TEXT DEFAULT 'local-user'"),
            ("comparisons",  "user_id TEXT DEFAULT 'local-user'"),
        ]
        from sqlalchemy import text
        for table, col_def in migrations:
            col_name = col_def.split()[0]
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
                print(f"[Migration] Added {col_name} to {table}")
            except Exception:
                pass  # Column already exists — safe to ignore
