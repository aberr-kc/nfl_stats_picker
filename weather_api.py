# Simple weather data for NFL games
def get_weather_for_game(team1, team2):
    """Get weather data for a game - simplified version"""
    # Sample weather data - in production this would call OpenWeatherMap API
    weather_data = {
        'temperature': -4.0,  # Celsius
        'wind_speed': 0.0,    # km/h
        'conditions': 'Clear'
    }
    
    # For Pittsburgh games, use cold weather
    if 'pittsburgh' in team1.lower() or 'pittsburgh' in team2.lower():
        weather_data['temperature'] = -4.0
        weather_data['conditions'] = 'Clear'
    
    return weather_data