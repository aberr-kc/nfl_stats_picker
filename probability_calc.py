from math import sqrt, pi, exp, erf

def calculate_probability(adjusted_avg, adjusted_std, betting_line, player_stats=None):
    """Calculate probability of going over/under betting line using normal distribution with enhanced variance modeling"""
    try:
        # Handle edge cases
        if adjusted_avg is None or betting_line is None:
            return 50.0, 50.0
            
        adjusted_avg = float(adjusted_avg)
        betting_line = float(betting_line)
        
        if adjusted_std is None or adjusted_std <= 0:
            # Enhanced std dev calculation based on multiple factors
            base_std = abs(adjusted_avg) * 0.25  # Increase base variance
            
            # Add variance based on sample size (fewer games = more uncertainty)
            if player_stats and 'weekly' in player_stats:
                games_played = len(player_stats['weekly'])
                if games_played < 3:
                    base_std *= 1.5  # 50% more variance for small samples
            
            # Add position-based variance (some positions more volatile)
            position_variance = {
                'QB': 0.2, 'RB': 0.35, 'WR': 0.4, 'TE': 0.45
            }
            
            # Use higher variance for more volatile stats
            if adjusted_avg > 0:
                if adjusted_avg < 50:  # Lower volume stats (receptions, TDs)
                    base_std = max(base_std, adjusted_avg * 0.4)
                else:  # Higher volume stats (yards)
                    base_std = max(base_std, adjusted_avg * 0.3)
            
            adjusted_std = max(base_std, 2.0)  # Minimum 2.0 std dev
        else:
            adjusted_std = float(adjusted_std)
            # Ensure minimum variance even with calculated std dev
            adjusted_std = max(adjusted_std, abs(adjusted_avg) * 0.2)
        
        # Add "bookmaker edge" - reduce extreme probabilities
        z_score = (betting_line - adjusted_avg) / adjusted_std
        
        # Use error function for accurate normal CDF
        prob_under = 0.5 * (1 + erf(z_score / sqrt(2)))
        prob_over = 1 - prob_under
        
        # Apply "market efficiency" adjustment - pull extreme probabilities toward 50%
        prob_over = prob_over * 0.85 + 0.15 * 0.5  # 15% pull toward 50%
        prob_under = prob_under * 0.85 + 0.15 * 0.5
        
        # Clamp probabilities to valid range [5, 95] to avoid overconfidence
        prob_over = max(5, min(95, prob_over * 100))
        prob_under = max(5, min(95, prob_under * 100))
        
        return round(prob_over, 1), round(prob_under, 1)
    except:
        return 50.0, 50.0

def add_probability_to_flagged(flagged_stat, adjusted_avg, adjusted_std, betting_line):
    """Add probability calculations to a flagged stat"""
    prob_over, prob_under = calculate_probability(adjusted_avg, adjusted_std, betting_line)
    flagged_stat['probabilityOver'] = prob_over
    flagged_stat['probabilityUnder'] = prob_under
    flagged_stat['adjustedStdDev'] = adjusted_std