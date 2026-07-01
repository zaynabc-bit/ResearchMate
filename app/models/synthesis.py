from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base
import uuid

class SynthesisReport(Base):
    __tablename__ = "synthesis_reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, default="Untitled Report")
    content = Column(Text, nullable=False)
    style = Column(String, nullable=False)
    custom_prompt = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
