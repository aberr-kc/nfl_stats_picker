import json

# Load existing team stats
with open('team_stats_data.json', 'r') as f:
    team_stats = json.load(f)

# Add estimated completions data for more teams to get proper league averages
teams_to_update = ['KC', 'BUF', 'DAL', 'DET', 'SF']

for team in teams_to_update:
    if team in team_stats:
        stats = team_stats[team]
        pass_yards = float(stats['pass_yards_game'])
        opp_pass_yards = float(stats['opp_pass_yards_game'])
        
        # Estimate completions (varies by team - some complete more, some less)
        team_completion_rates = {
            'KC': (0.68, 0.65),    # KC completes well, allows average
            'BUF': (0.66, 0.62),   # BUF solid, good defense
            'DAL': (0.64, 0.70),   # DAL average offense, poor defense
            'DET': (0.67, 0.68),   # DET good offense, average defense  
            'SF': (0.65, 0.64)     # SF solid both ways
        }
        
        off_rate, def_rate = team_completion_rates[team]
        
        # Estimate passes per game (pass yards / ~7.5 yards per pass)
        passes_game = pass_yards / 7.5
        opp_passes_game = opp_pass_yards / 7.5
        
        completions_game = round(passes_game * off_rate, 1)
        opp_completions_game = round(opp_passes_game * def_rate, 1)
        
        stats['completions_game'] = str(completions_game)
        stats['opp_completions_game'] = str(opp_completions_game)
        
        print(f"{team}: {completions_game} comp/game, allows {opp_completions_game} comp/game")

# Save updated data
with open('team_stats_data.json', 'w') as f:
    json.dump(team_stats, f, indent=2)

print("Added completions data for more teams")