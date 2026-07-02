from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid



class ResearchPaper(Base):
    __tablename__ = "papers"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    authors = Column(String, nullable=True)
    journal = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    abstract = Column(Text, nullable=True)
    extracted_text = Column(Text, nullable=True)
    file_url = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)

    # AI-generated fields
    summary = Column(Text, nullable=True)
    research_aim = Column(Text, nullable=True)
    methodology = Column(Text, nullable=True)
    key_findings = Column(Text, nullable=True)
    limitations = Column(Text, nullable=True)
    strengths = Column(Text, nullable=True)
    weaknesses = Column(Text, nullable=True)
    future_work = Column(Text, nullable=True)
    keywords = Column(String, nullable=True)  # JSON array as string
    summary_status = Column(String, default="none")  # none | generating | done | error

    notes = Column(Text, default="")
    is_favourite = Column(Boolean, default=False)
    custom_header = Column(Text, nullable=True)

    folder_id = Column(String, ForeignKey("folders.id"), nullable=True)
    folder = relationship("Folder", back_populates="papers")
    chunks = relationship("PaperChunk", back_populates="paper", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="paper", cascade="all, delete-orphan")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    read_count = Column(Integer, default=0)
    last_opened = Column(DateTime(timezone=True), nullable=True)
