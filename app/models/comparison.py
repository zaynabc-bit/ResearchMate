from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid

class PaperComparison(Base):
    __tablename__ = "comparisons"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    
    paper_a_id = Column(String, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    paper_b_id = Column(String, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    
    # JSON-serialised data containing the comparison tables, narratives, and indicators
    comparison_data = Column(Text, nullable=False)
    
    paper_a = relationship("ResearchPaper", foreign_keys=[paper_a_id])
    paper_b = relationship("ResearchPaper", foreign_keys=[paper_b_id])

    created_at = Column(DateTime(timezone=True), server_default=func.now())
