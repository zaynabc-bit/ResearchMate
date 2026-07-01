from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func
from app.database import Base
import uuid

class SavedRewrite(Base):
    __tablename__ = "rewrites"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    original_text = Column(Text, nullable=False)
    rewritten_text = Column(Text, nullable=False)
    mode = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
