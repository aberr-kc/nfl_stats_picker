import requests
from bs4 import BeautifulSoup
import urllib3
import json

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def scrape_team_stats(team_abbreviation):
    """Scrape team stats from teamrankings.com"""
    url = f"https://www.teamrankings.com/nfl/team/{team_abbreviation.lower()}"
    
    try:
        response = requests.get(url, verify=False, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        stats = {}
        
        # Find all stat tables
        tables = soup.find_all('table', class_='tr-table')
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    stat_name = cells[0].get_text(strip=True)
                    stat_value = cells[1].get_text(strip=True)
                    
                    # Extract numeric value
                    if '(' in stat_value:
                        stat_value = stat_value.split('(')[0].strip()
                    
                    # Map stats
                    if 'Rush Yards/Game' in stat_name:
                        stats['rush_yards_game'] = stat_value
                    elif 'Pass Yards/Game' in stat_name:
                        stats['pass_yards_game'] = stat_value
                    elif 'Opp Rush Yards/Game' in stat_name:
                        stats['opp_rush_yards_game'] = stat_value
                    elif 'Opp Pass Yards/Game' in stat_name:
                        stats['opp_pass_yards_game'] = stat_value
                    elif 'Completion %' in stat_name:
                        stats['completion_pct'] = float(stat_value.replace('%', ''))
                    elif 'Opp Completion %' in stat_name:
                        stats['opp_completion_pct'] = float(stat_value.replace('%', ''))
                    elif 'Yards/Pass' in stat_name:
                        stats['yards_per_pass'] = float(stat_value)
                    elif 'Opp Yards/Pass' in stat_name:
                        stats['opp_yards_per_pass'] = float(stat_value)
                    elif 'Passes/Game' in stat_name:
                        stats['passes_game'] = float(stat_value)
                    elif 'Opp Passes/Game' in stat_name:
                        stats['opp_passes_game'] = float(stat_value)
        
        # Calculate completions per game
        if 'passes_game' in stats and 'completion_pct' in stats:
            passes = stats['passes_game']
            completions_game = round(passes * (stats['completion_pct'] / 100), 1)
            stats['completions_game'] = str(completions_game)
        
        if 'opp_passes_game' in stats and 'opp_completion_pct' in stats:
            opp_passes = stats['opp_passes_game']
            opp_completions_game = round(opp_passes * (stats['opp_completion_pct'] / 100), 1)
            stats['opp_completions_game'] = str(opp_completions_game)
        
        return stats
        
    except Exception as e:
        print(f"Error scraping {team_abbreviation}: {e}")
        return {}

def update_all_team_stats():
    """Update stats for all NFL teams"""
    teams = [
        'ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN',
        'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC', 'LV', 'LAC', 'LAR', 'MIA',
        'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SF', 'SEA', 'TB', 'TEN', 'WAS'
    ]
    
    all_stats = {}
    
    for team in teams:
        print(f"Scraping {team}...")
        stats = scrape_team_stats(team)
        if stats:
            all_stats[team] = stats
            print(f"  ✓ {team}: {stats.get('completions_game', 'N/A')} comp/game, allows {stats.get('opp_completions_game', 'N/A')} comp/game")
    
    # Save to file
    with open('team_stats_data.json', 'w') as f:
        json.dump(all_stats, f, indent=2)
    
    print(f"\nUpdated stats for {len(all_stats)} teams")
    return all_stats

def get_team_stats_for_player(team_abbreviation):
    """Get team stats from saved data"""
    saved_stats = load_saved_team_stats()
    
    if team_abbreviation in saved_stats:
        return saved_stats[team_abbreviation]
    
    # Fallback sample data
    sample_data = {
        'ARI': {'rush_yards_game': '110.5', 'pass_yards_game': '245.2', 'opp_pass_yards_game': '220.1', 'opp_rush_yards_game': '125.3'},
        'BUF': {'rush_yards_game': '125.8', 'pass_yards_game': '280.4', 'opp_pass_yards_game': '195.7', 'opp_rush_yards_game': '105.2'},
        'KC': {'rush_yards_game': '115.2', 'pass_yards_game': '295.6', 'opp_pass_yards_game': '210.8', 'opp_rush_yards_game': '118.9'}
    }
    return sample_data.get(team_abbreviation, {'rush_yards_game': '120.0', 'pass_yards_game': '250.0', 'opp_pass_yards_game': '215.0', 'opp_rush_yards_game': '115.0'})

def load_saved_team_stats():
    """Load team stats from saved JSON file"""
    try:
        import json
        with open('team_stats_data.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def get_league_averages():
    """Calculate league averages from saved data"""
    saved_stats = load_saved_team_stats()
    
    rush_values = []
    pass_values = []
    
    for team_stats in saved_stats.values():
        if team_stats.get('rush_yards_game'):
            try:
                rush_values.append(float(team_stats['rush_yards_game']))
            except:
                pass
                
        if team_stats.get('pass_yards_game'):
            try:
                pass_values.append(float(team_stats['pass_yards_game']))
            except:
                pass
    
    league_avg_rush = sum(rush_values) / len(rush_values) if rush_values else 120.0
    league_avg_pass = sum(pass_values) / len(pass_values) if pass_values else 250.0
    
    return {
        'rush_yards_game': round(league_avg_rush, 1),
        'pass_yards_game': round(league_avg_pass, 1)
    }

def get_league_defensive_averages():
    """Calculate league defensive averages from saved data"""
    saved_stats = load_saved_team_stats()
    
    opp_rush_values = []
    opp_pass_values = []
    opp_completions_values = []
    
    for team_stats in saved_stats.values():
        if team_stats.get('opp_rush_yards_game'):
            try:
                opp_rush_values.append(float(team_stats['opp_rush_yards_game']))
            except:
                pass
                
        if team_stats.get('opp_pass_yards_game'):
            try:
                opp_pass_values.append(float(team_stats['opp_pass_yards_game']))
            except:
                pass
                
        if team_stats.get('opp_completions_game'):
            try:
                opp_completions_values.append(float(team_stats['opp_completions_game']))
            except:
                pass
    
    league_avg_opp_rush = sum(opp_rush_values) / len(opp_rush_values) if opp_rush_values else 115.0
    league_avg_opp_pass = sum(opp_pass_values) / len(opp_pass_values) if opp_pass_values else 215.0
    league_avg_opp_completions = sum(opp_completions_values) / len(opp_completions_values) if opp_completions_values else 22.0
    
    return {
        'opp_rush_yards_game': round(league_avg_opp_rush, 1),
        'opp_pass_yards_game': round(league_avg_opp_pass, 1),
        'opp_completions_game': round(league_avg_opp_completions, 1)
    }

def display_team_stats(team_stats):
    """Display team stats"""
    if not team_stats:
        print("    No team stats available")
        return
    
    rush_value = team_stats.get('rush_yards_game', 'N/A')
    pass_value = team_stats.get('pass_yards_game', 'N/A')
    opp_pass_value = team_stats.get('opp_pass_yards_game', 'N/A')
    opp_rush_value = team_stats.get('opp_rush_yards_game', 'N/A')
    print(f"    Team Statistics:")
    print(f"      Rush Yards/Game: {rush_value}")
    print(f"      Pass Yards/Game: {pass_value}")
    print(f"      Opp Pass Yards/Game: {opp_pass_value}")
    print(f"      Opp Rush Yards/Game: {opp_rush_value}")