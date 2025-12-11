import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def debug_scrape_phi():
    """Debug scrape PHI to see what fields are available"""
    url = "https://www.teamrankings.com/nfl/team/philadelphia-eagles"
    
    try:
        response = requests.get(url, verify=False, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        print("=== ALL STAT NAMES FOUND ===")
        tables = soup.find_all('table', class_='tr-table')
        
        all_stats = []
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 2:
                    stat_name = cells[0].get_text(strip=True)
                    stat_value = cells[1].get_text(strip=True)
                    all_stats.append((stat_name, stat_value))
                    print(f"'{stat_name}' = '{stat_value}'")
        
        print(f"\n=== TOTAL STATS FOUND: {len(all_stats)} ===")
        
        # Look for completion-related stats
        print("\n=== COMPLETION-RELATED STATS ===")
        for stat_name, stat_value in all_stats:
            if 'completion' in stat_name.lower() or 'complete' in stat_name.lower():
                print(f"FOUND: '{stat_name}' = '{stat_value}'")
        
        # Look for yards/pass stats
        print("\n=== YARDS/PASS STATS ===")
        for stat_name, stat_value in all_stats:
            if 'yards/pass' in stat_name.lower() or 'per pass' in stat_name.lower():
                print(f"FOUND: '{stat_name}' = '{stat_value}'")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_scrape_phi()