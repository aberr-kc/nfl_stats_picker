# Weather adjustment factors for NFL stats
def get_weather_adjustments(temperature, wind_speed, conditions):
    """Get weather adjustment factors for different stats"""
    adjustments = {
        'passing_yards': 1.0,
        'receiving_yards': 1.0, 
        'rushing_yards': 1.0,
        'receptions': 1.0
    }
    
    # No weather data (weather_api has no real source yet): stay neutral
    # instead of guessing, so no game gets a weather adjustment.
    if temperature is None or wind_speed is None or conditions is None:
        return adjustments
    
    # Temperature adjustments
    if temperature < 0:  # Very cold
        adjustments['passing_yards'] *= 0.92  # -8%
        adjustments['receiving_yards'] *= 0.92
        adjustments['rushing_yards'] *= 1.05  # +5%
        adjustments['receptions'] *= 0.95
    elif temperature < 10:  # Cold
        adjustments['passing_yards'] *= 0.95  # -5%
        adjustments['receiving_yards'] *= 0.95
        adjustments['rushing_yards'] *= 1.02  # +2%
        adjustments['receptions'] *= 0.98
    
    # Wind adjustments
    if wind_speed > 25:  # Very windy
        adjustments['passing_yards'] *= 0.85  # -15%
        adjustments['receiving_yards'] *= 0.85
        adjustments['receptions'] *= 0.90
    elif wind_speed > 15:  # Windy
        adjustments['passing_yards'] *= 0.92  # -8%
        adjustments['receiving_yards'] *= 0.92
        adjustments['receptions'] *= 0.95
    
    # Precipitation adjustments
    if 'rain' in conditions.lower() or 'snow' in conditions.lower():
        adjustments['passing_yards'] *= 0.90  # -10%
        adjustments['receiving_yards'] *= 0.90
        adjustments['rushing_yards'] *= 1.03  # +3%
        adjustments['receptions'] *= 0.92
    
    return adjustments

def format_weather_explanation(temperature, wind_speed, conditions):
    """Format weather explanation text"""
    if temperature is None or wind_speed is None or conditions is None:
        return "No weather data (adjustment disabled)"
    
    explanations = []
    
    if temperature < 0:
        explanations.append("very cold")
    elif temperature < 10:
        explanations.append("cold")
    
    if wind_speed > 25:
        explanations.append("very windy")
    elif wind_speed > 15:
        explanations.append("windy")
    
    if 'rain' in conditions.lower():
        explanations.append("rain")
    elif 'snow' in conditions.lower():
        explanations.append("snow")
    
    if explanations:
        return f"{temperature}°C, {wind_speed}km/h wind ({', '.join(explanations)})"
    else:
        return f"{temperature}°C, {wind_speed}km/h wind"