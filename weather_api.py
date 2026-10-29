# Weather data for NFL games
#
# No real weather source is wired in yet. The previous version returned a
# hardcoded -4.0 C for every game, which made weather_adjustments apply the
# "very cold" penalty to every matchup (domes included).
#
# Until a real source is added, this returns "no data" (all values None and
# available=False). weather_adjustments treats that as neutral (factor 1.0).
#
# To plug in a real source (e.g. OpenWeatherMap by stadium location, with
# dome/retractable-roof handling), fill in temperature (Celsius),
# wind_speed (km/h) and conditions (e.g. 'Clear', 'Rain', 'Snow') here and
# set available=True.
def get_weather_for_game(team1, team2):
    """Get weather data for a game. Returns no-data values until a real source exists."""
    return {
        'temperature': None,  # Celsius
        'wind_speed': None,   # km/h
        'conditions': None,
        'available': False
    }
