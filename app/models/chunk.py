from sqlalchemy import Column, String, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
import uuid


class PaperChunk(Base):
    """Stores text chunks and their nomic-embed-text embeddings for RAG."""
    __tablename__ = "paper_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    paper_id = Column(String, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # JSON-encoded float list

    paper = relationship("ResearchPaper", back_populates="chunks")
