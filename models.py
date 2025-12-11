# models.py - SQLAlchemy database models

from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

# Create engine and base
engine = create_engine("sqlite:///nfl_stats.db")
Base = declarative_base()
Session = sessionmaker(bind=engine)

class Player(Base):
    __tablename__ = "players"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)

class Odds(Base):
    __tablename__ = "odds"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(String, nullable=False)
    event_id = Column(String)
    event_name = Column(String)
    bookmaker = Column(String, nullable=False)
    market = Column(String, nullable=False)
    line = Column(Float)
    price = Column(Float)
    season = Column(Integer)
    week = Column(Integer)
    retrieved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Create tables
Base.metadata.create_all(engine)