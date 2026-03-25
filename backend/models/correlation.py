from datetime import datetime
from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, Text, TIMESTAMP
from backend.database import Base


class PoolCorrelation(Base):
    __tablename__ = "pool_correlations"

    alpha_a = Column(Text, ForeignKey("alphas.id"), primary_key=True)
    alpha_b = Column(Text, ForeignKey("alphas.id"), primary_key=True)
    correlation = Column(Float, nullable=False)
    computed_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(Text, nullable=False)
    candidates_gen = Column(Integer, nullable=False, default=0)
    candidates_pass = Column(Integer, nullable=False, default=0)
    llm_theme = Column(Text, nullable=True)
    gp_generations = Column(Integer, nullable=True)
    started_at = Column(TIMESTAMP, nullable=False, default=datetime.utcnow)
    finished_at = Column(TIMESTAMP, nullable=True)


class ProxyPrice(Base):
    __tablename__ = "proxy_prices"

    ticker = Column(Text, primary_key=True)
    date = Column(Text, primary_key=True)
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    adj_close = Column(Float, nullable=True)
    volume = Column(Integer, nullable=True)
