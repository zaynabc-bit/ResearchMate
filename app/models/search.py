from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.database import Base
import uuid

class DiscoverSearch(Base):
    __tablename__ = "discover_searches"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    query = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
