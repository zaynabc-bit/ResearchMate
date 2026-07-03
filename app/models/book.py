from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid

class Book(Base):
    __tablename__ = "books"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=True)
    file_url = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    
    # Global AI fields
    overall_summary = Column(Text, nullable=True)
    executive_summary = Column(Text, nullable=True)
    key_themes = Column(Text, nullable=True)
    key_concepts = Column(Text, nullable=True)
    important_arguments = Column(Text, nullable=True)
    important_quotes = Column(Text, nullable=True)
    definitions = Column(Text, nullable=True)
    glossary = Column(Text, nullable=True)
    timeline = Column(Text, nullable=True)
    people = Column(Text, nullable=True)
    places = Column(Text, nullable=True)
    events = Column(Text, nullable=True)
    final_conclusions = Column(Text, nullable=True)
    
    # State tracking
    processing_status = Column(String, default="pending") # pending | processing | chunking | summarizing | done | error
    progress_percent = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    chapters = relationship("BookChapter", back_populates="book", cascade="all, delete-orphan")
    chunks = relationship("BookChunk", back_populates="book", cascade="all, delete-orphan")
    notes = relationship("BookNote", back_populates="book", cascade="all, delete-orphan")
    study_tools = relationship("BookStudyTool", back_populates="book", cascade="all, delete-orphan")
    chat_messages = relationship("BookChatMessage", back_populates="book", cascade="all, delete-orphan")

class BookChapter(Base):
    __tablename__ = "book_chapters"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_index = Column(Integer, nullable=False)
    title = Column(String, nullable=True)
    text_content = Column(Text, nullable=False)
    
    # AI Summaries
    summary = Column(Text, nullable=True)
    key_ideas = Column(Text, nullable=True)
    important_quotes = Column(Text, nullable=True)
    definitions = Column(Text, nullable=True)
    
    book = relationship("Book", back_populates="chapters")

class BookChunk(Base):
    """Stores text chunks and their nomic-embed-text embeddings for RAG."""
    __tablename__ = "book_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(String, ForeignKey("book_chapters.id", ondelete="CASCADE"), nullable=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # JSON-encoded float list

    book = relationship("Book", back_populates="chunks")

class BookNote(Base):
    __tablename__ = "book_notes"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(String, ForeignKey("book_chapters.id", ondelete="CASCADE"), nullable=True)
    content = Column(Text, nullable=False)
    tags = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    book = relationship("Book", back_populates="notes")

class BookStudyTool(Base):
    __tablename__ = "book_study_tools"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    tool_type = Column(String, nullable=False) # flashcards | revision_notes | practice_questions | key_definitions | checklist
    content = Column(Text, nullable=False) # JSON format usually
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    book = relationship("Book", back_populates="study_tools")

class BookChatMessage(Base):
    __tablename__ = "book_chat_messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    book = relationship("Book", back_populates="chat_messages")
