from datetime import datetime
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, Text, TIMESTAMP
from backend.database import Base


class Simulation(Base):
    __tablename__ = "simulations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alpha_id = Column(Text, ForeignKey("alphas.id"), nullable=False)
    sharpe = Column(Float, nullable=True)
    fitness = Column(Float, nullable=True)
    returns = Column(Float, nullable=True)
    turnover = Column(Float, nullable=True)
    passed = Column(Boolean, nullable=True)
    status = Column(Text, nullable=False, default="pending")
    submitted_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    wq_sim_id = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
