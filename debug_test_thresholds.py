from test_thresholds import get_recent_3_game_stats, get_odds_for_player
from team_stats import get_team_stats_for_player, get_league_defensive_averages

# Test Dalton Schultz specifically
player_name = "Dalton Schultz"
season = 2025
week = 12

print(f"=== Testing {player_name} ===")

# Get player stats
player_stats = get_recent_3_game_stats(season, player_name, week)
if player_stats:
    print(f"Player avg receptions: {player_stats['avg'].get('receptions', 'N/A')}")
    print(f"Has adjusted_receptions: {'adjusted_receptions' in player_stats['avg']}")
    print(f"Has receptions_adjustment_pct: {'receptions_adjustment_pct' in player_stats['avg']}")
else:
    print("No player stats found")

# Get odds to find opponent
odds = get_odds_for_player(player_name)
if odds:
    event_name = odds[0].get('event_name', '')
    print(f"Event: {event_name}")
    
    if 'vs' in event_name:
        teams = event_name.split(' vs ')
        print(f"Teams: {teams}")
        
        # Check if BUF is opponent
        if 'Buffalo' in event_name:
            print("Buffalo is the opponent - should have adjustment")
            buf_stats = get_team_stats_for_player('BUF')
            league_def = get_league_defensive_averages()
            
            if buf_stats.get('opp_completions_game') and league_def.get('opp_completions_game'):
                opp_comp = float(buf_stats['opp_completions_game'])
                league_comp = float(league_def['opp_completions_game'])
                multiplier = opp_comp / league_comp
                print(f"Should adjust by {multiplier:.3f} ({(multiplier-1)*100:+.1f}%)")
            else:
                print("Missing completions data for adjustment")
else:
    print("No odds found")