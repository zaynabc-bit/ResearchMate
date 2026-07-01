from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import uuid


class Folder(Base):
    __tablename__ = "folders"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    colour = Column(String, default="#6366f1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    papers = relationship("ResearchPaper", back_populates="folder")
