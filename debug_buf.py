from team_stats import get_team_stats_for_player, get_league_defensive_averages

# Check BUF team stats (Dalton Schultz opponent)
buf_stats = get_team_stats_for_player('BUF')
print("BUF team stats:", buf_stats)

# Check if BUF has completions data
if buf_stats.get('opp_completions_game'):
    league_def = get_league_defensive_averages()
    print(f"BUF allows {buf_stats['opp_completions_game']} completions/game")
    print(f"League average: {league_def.get('opp_completions_game', 'N/A')} completions/game")
    
    if league_def.get('opp_completions_game'):
        opp_comp = float(buf_stats['opp_completions_game'])
        league_comp = float(league_def['opp_completions_game'])
        multiplier = opp_comp / league_comp
        print(f"Adjustment multiplier: {multiplier:.3f} ({(multiplier-1)*100:+.1f}%)")
        
        # Test receptions adjustment
        original_receptions = 6.3
        adjusted_receptions = round(original_receptions * multiplier, 1)
        print(f"Dalton Schultz: {original_receptions} -> {adjusted_receptions} receptions")
else:
    print("BUF has no completions data - need to add it.")