# models.py - SQLAlchemy database models

from pathlib import Path
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

# Create engine and base (absolute path so imports from another cwd don't create a stray DB)
DB_PATH = Path(__file__).resolve().parent / "nfl_stats.db"
engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}")
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
    season_type = Column(String, default='regular')  # 'regular' or 'playoffs'
    retrieved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Weather(Base):
    __tablename__ = "weather"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False)
    temperature = Column(Float)  # Fahrenheit
    wind_speed = Column(Float)   # mph
    precipitation = Column(Float)  # inches
    conditions = Column(String)  # Clear, Rain, Snow, etc.
    season = Column(Integer)
    week = Column(Integer)
    season_type = Column(String, default='regular')  # 'regular' or 'playoffs'
    retrieved_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

def ensure_season_type_columns(engine):
    """Add season_type to tables created before the column existed.

    create_all() never alters existing tables, so older DBs lack this column.
    Idempotent: only runs ALTER TABLE when the column is missing.
    """
    with engine.begin() as conn:
        for table in ("odds", "weather"):  # fixed literals, not user input
            columns = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]
            if columns and "season_type" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN season_type TEXT DEFAULT 'regular'"))

# Create tables
Base.metadata.create_all(engine)
ensure_season_type_columns(engine)
