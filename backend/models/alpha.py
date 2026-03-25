from datetime import datetime
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, Text, TIMESTAMP
from backend.database import Base


class Alpha(Base):
    __tablename__ = "alphas"

    id = Column(Text, primary_key=True)
    expression = Column(Text, nullable=False)
    universe = Column(Text, nullable=False, default="TOP3000")
    region = Column(Text, nullable=False, default="USA")
    delay = Column(Integer, nullable=False, default=1)
    decay = Column(Integer, nullable=False, default=0)
    neutralization = Column(Text, nullable=False, default="subindustry")
    truncation = Column(Float, nullable=False, default=0.08)
    pasteurization = Column(Text, nullable=False, default="off")
    nan_handling = Column(Text, nullable=False, default="off")
    source = Column(Text, nullable=False)
    parent_id = Column(Text, ForeignKey("alphas.id"), nullable=True)
    rationale = Column(Text, nullable=True)
    filter_skipped = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
