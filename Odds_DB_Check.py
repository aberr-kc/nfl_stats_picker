# Odds DB Check - Full View
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, Odds, Player

# --- Setup ---
engine = create_engine("sqlite:///nfl_stats.db")
Session = sessionmaker(bind=engine)
session = Session()

# --- Fetch all odds ---
odds_entries = session.query(Odds).all()

# --- Organize by event and market ---
events_dict = {}

for odds in odds_entries:
    event_key = f"{odds.event_name} ({odds.event_id})"
    if event_key not in events_dict:
        events_dict[event_key] = {}

    market_key = odds.market
    if market_key not in events_dict[event_key]:
        events_dict[event_key][market_key] = []

    events_dict[event_key][market_key].append({
        "player": odds.player_id,
        "line": odds.line,
        "price": odds.price
    })

# --- Print nicely ---
for event_name, markets in events_dict.items():
    print(f"\n🎯 Event: {event_name}")
    for market_name, outcomes in markets.items():
        print(f"  Market: {market_name}")
        for outcome in outcomes:
            line_str = f"{outcome['line']}" if outcome['line'] is not None else "N/A"
            print(f"    Player: {outcome['player']}, Line: {line_str}, Price: {outcome['price']}")

