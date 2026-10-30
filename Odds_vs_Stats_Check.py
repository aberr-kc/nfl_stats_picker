# odds_vs_stats_check.py
import pandas as pd
import numpy as np

def compute_player_stats(rows):
    """
    Compute averages and std dev for numeric stats across last 5 games only.
    If only 1 game exists, return raw stats with std=0.
    """
    if not rows:
        return {"avg": {}, "std": {}}

    # Take only the last 5 weeks
    recent_rows = rows[-5:]
    df = pd.DataFrame(recent_rows)

    # Only include actual stat columns, exclude metadata
    stat_cols = ['passing_yards', 'passing_tds', 'rushing_yards', 'rushing_tds', 
                 'receiving_yards', 'receiving_tds', 'receptions']
    
    # Keep only stat columns that exist and are numeric
    available_cols = [c for c in stat_cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    df = df[available_cols]

    if len(df) == 1:
        # ✅ Only one game played → use raw stats
        avg = df.iloc[0].to_dict()
        std = {c: 0.0 for c in avg}
        return {"avg": avg, "std": std}

    # Multiple games - calculate average and standard deviation for last 5 weeks
    avg = df.mean().to_dict()
    std = df.std().to_dict()

    return {"avg": avg, "std": std}




def check_stat_against_odds(player_name, player_stats, odds, thresholds):
    """
    Compare player stats vs betting odds using adaptive thresholds.

    Returns only unique flagged stats per player/stat/bookmaker.
    """
    flagged = []
    seen = set()  # to deduplicate

    MARKET_MAP = {
        "player_pass_yds": "passing_yards",
        "player_pass_tds": "passing_tds",
        "player_reception_yds": "receiving_yards",
        "player_receptions": "receptions",
        "player_rush_yds": "rushing_yards",
    }

    for o in odds:
        market = o.get("market")
        line = o.get("line")
        bookmaker = o.get("bookmaker")
        prices = dict(o.get("prices") or {})

        if line is None:
            continue

        stat_key = MARKET_MAP.get(market)
        if not stat_key:
            continue

        if stat_key not in player_stats["avg"]:
            continue

        # Skip if player has all zeros in last 5 weeks for this stat
        if "weekly" in player_stats:
            recent_values = [week.get(stat_key, 0) for week in player_stats["weekly"][-5:]]
            if all(v == 0 for v in recent_values):
                continue

        # Deduplicate based on player/stat/bookmaker
        dedup_key = (player_name, stat_key, bookmaker)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        avg_val = player_stats["avg"][stat_key]
        std_val = player_stats["std"].get(stat_key, 0)
        difference = avg_val - line
        threshold_value = thresholds.get(stat_key, 15)

        if difference >= threshold_value:
            verdict = "Over"
        elif difference <= -threshold_value:
            verdict = "Under"
        else:
            verdict = "No Bet"

        if verdict != "No Bet":
            # Get adjusted stat value if available
            adjusted_passing = player_stats["avg"].get("adjusted_passing_yards", None)
            adjusted_rushing = player_stats["avg"].get("adjusted_rushing_yards", None)
            adjusted_receiving = player_stats["avg"].get("adjusted_receiving_yards", None)
            adjusted_receptions = player_stats["avg"].get("adjusted_receptions", None)
            
            # Get adjustment percentages
            pass_adj_pct = player_stats["avg"].get("pass_adjustment_pct", 0)
            rush_adj_pct = player_stats["avg"].get("rush_adjustment_pct", 0)
            receptions_adj_pct = player_stats["avg"].get("receptions_adjustment_pct", 0)
            
            # Create adjustment details
            adjustment_details = None
            if stat_key == "passing_yards" and pass_adj_pct != 0:
                direction = "easier" if pass_adj_pct > 0 else "tougher"
                adjustment_details = {
                    "changePct": pass_adj_pct,
                    "explanation": f"Matchup: Opponent allows {abs(pass_adj_pct):.1f}% {'more' if pass_adj_pct > 0 else 'fewer'} pass yards than league avg - {direction} matchup"
                }
            elif stat_key == "receiving_yards" and pass_adj_pct != 0:
                direction = "easier" if pass_adj_pct > 0 else "tougher"
                adjustment_details = {
                    "changePct": pass_adj_pct,
                    "explanation": f"Matchup: Opponent allows {abs(pass_adj_pct):.1f}% {'more' if pass_adj_pct > 0 else 'fewer'} pass yards than league avg - {direction} matchup for receivers"
                }
            elif stat_key == "rushing_yards" and rush_adj_pct != 0:
                direction = "easier" if rush_adj_pct > 0 else "tougher"
                adjustment_details = {
                    "changePct": rush_adj_pct,
                    "explanation": f"Matchup: Opponent allows {abs(rush_adj_pct):.1f}% {'more' if rush_adj_pct > 0 else 'fewer'} rush yards than league avg - {direction} matchup for rushers"
                }
            elif stat_key == "receptions" and receptions_adj_pct != 0:
                direction = "easier" if receptions_adj_pct > 0 else "tougher"
                adjustment_details = {
                    "changePct": receptions_adj_pct,
                    "explanation": f"Matchup: Opponent allows {abs(receptions_adj_pct):.1f}% {'more' if receptions_adj_pct > 0 else 'fewer'} completions than league avg - {direction} matchup for targets"
                }
            
            # Calculate probabilities
            from probability_calc import calculate_probability
            prob_over, prob_under = calculate_probability(avg_val, std_val, line, player_stats)
            
            flagged.append(
                {
                    "player_name": player_name,
                    "stat": stat_key,
                    "player_value": round(avg_val, 1),
                    "line": line,
                    "difference": round(difference, 1),
                    "std_dev": round(std_val, 1) if std_val is not None else None,
                    "threshold_rule": verdict,
                    "bookmaker": bookmaker,
                    "adjustedPassingYards": adjusted_passing,
                    "adjustedRushingYards": adjusted_rushing,
                    "adjustedReceivingYards": adjusted_receiving,
                    "adjustedReceptions": adjusted_receptions,
                    "adjustmentDetails": adjustment_details,
                    "probabilityOver": prob_over,
                    "probabilityUnder": prob_under,
                    # Prices by outcome ({"Over": .., "Under": ..}; {"unknown": ..} for old rows)
                    "prices": prices,
                    "pickPrice": prices.get(verdict),
                }
            )

    return flagged
