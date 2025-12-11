from team_stats import get_team_stats_for_player, get_league_defensive_averages

# Check PHI team stats
phi_stats = get_team_stats_for_player('PHI')
print("PHI team stats:", phi_stats)

# Check league defensive averages
league_def = get_league_defensive_averages()
print("League defensive averages:", league_def)

# Check if PHI has completions data
if phi_stats.get('opp_completions_game'):
    print(f"PHI allows {phi_stats['opp_completions_game']} completions/game")
    print(f"League average: {league_def.get('opp_completions_game', 'N/A')} completions/game")
    
    if league_def.get('opp_completions_game'):
        opp_comp = float(phi_stats['opp_completions_game'])
        league_comp = float(league_def['opp_completions_game'])
        multiplier = opp_comp / league_comp
        print(f"Adjustment multiplier: {multiplier:.3f} ({(multiplier-1)*100:+.1f}%)")
else:
    print("PHI has no completions data")