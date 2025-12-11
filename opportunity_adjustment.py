# opportunity_adjustment.py - Adjust stats and variance based on opportunity

def adjust_stats_for_opportunity(player_stats, opponent_stats=None, league_averages=None, player_team=None, event_name=None, season=None, week=None):
    """
    Adjust player statistics and standard deviation based on:
    1. Opportunity (reception share)
    2. Opponent matchup
    3. Game script (spread-based)
    """
    if not player_stats:
        return player_stats
    
    reception_share = player_stats.get("reception_share", 0)
    rushing_opportunity = player_stats.get("rushing_opportunity", 0)
    
    # Create adjusted stats copy
    adjusted_stats = player_stats.copy()
    adjusted_avg = adjusted_stats["avg"].copy()
    adjusted_std = adjusted_stats["std"].copy()
    
    # Track original values for comparison
    original_avg = adjusted_avg.copy()
    
    # Apply game script adjustments first
    game_script_applied = False
    if player_team and event_name and season and week:
        try:
            from game_script_adjustment import apply_game_script_adjustment, get_game_spread
            spread = get_game_spread(event_name, season, week)
            if spread != 0:
                adjusted_stats = apply_game_script_adjustment(adjusted_stats, player_team, event_name, season, week)
                adjusted_avg = adjusted_stats["avg"].copy()
                game_script_applied = True
        except Exception as e:
            print(f"Game script adjustment failed: {e}")
            pass
    
    # Adjust standard deviation based on opportunity share
    # High opportunity = lower variance, Low opportunity = higher variance
    for stat_name in ["receiving_yards", "receptions"]:
        if stat_name in adjusted_std:
            if reception_share > 0.20:  # High target share (>20%)
                adjusted_std[stat_name] = adjusted_std[stat_name] * 0.8  # Lower variance
            elif reception_share < 0.10:  # Low target share (<10%)
                adjusted_std[stat_name] = adjusted_std[stat_name] * 1.3  # Higher variance
            # Medium target share (10-20%) keeps normal variance
    
    # Adjust rushing stats based on rushing opportunity
    for stat_name in ["rushing_yards", "rushing_tds"]:
        if stat_name in adjusted_std:
            if rushing_opportunity > 0.25:  # High rushing opportunity
                adjusted_std[stat_name] = adjusted_std[stat_name] * 0.85
            elif rushing_opportunity < 0.15:  # Low rushing opportunity  
                adjusted_std[stat_name] = adjusted_std[stat_name] * 1.2
    
    # Apply opponent adjustments if available (existing logic)
    if opponent_stats and league_averages:
        # Receiving yards adjustment
        if opponent_stats.get('opp_pass_yards_game') != 'N/A' and league_averages.get('opp_pass_yards_game'):
            try:
                opp_pass_def = float(opponent_stats['opp_pass_yards_game'])
                league_pass_def = float(league_averages['opp_pass_yards_game'])
                pass_multiplier = opp_pass_def / league_pass_def if league_pass_def > 0 else 1
                
                if 'receiving_yards' in adjusted_avg:
                    adjusted_avg['receiving_yards'] = adjusted_avg['receiving_yards'] * pass_multiplier
                    adjusted_std['receiving_yards'] = adjusted_std['receiving_yards'] * pass_multiplier
                if 'passing_yards' in adjusted_avg:
                    adjusted_avg['passing_yards'] = adjusted_avg['passing_yards'] * pass_multiplier
                    adjusted_std['passing_yards'] = adjusted_std['passing_yards'] * pass_multiplier
            # amazonq-ignore-next-line
            except:
                pass
        
        # Rushing yards adjustment
        if opponent_stats.get('opp_rush_yards_game') != 'N/A' and league_averages.get('opp_rush_yards_game'):
            try:
                opp_rush_def = float(opponent_stats['opp_rush_yards_game'])
                league_rush_def = float(league_averages['opp_rush_yards_game'])
                rush_multiplier = opp_rush_def / league_rush_def if league_rush_def > 0 else 1
                
                if 'rushing_yards' in adjusted_avg:
                    adjusted_avg['rushing_yards'] = adjusted_avg['rushing_yards'] * rush_multiplier
                    adjusted_std['rushing_yards'] = adjusted_std['rushing_yards'] * rush_multiplier
            # amazonq-ignore-next-line
            except:
                pass
    
    adjusted_stats["avg"] = adjusted_avg
    adjusted_stats["std"] = adjusted_std
    
    # Add adjustment tracking
    adjustments = {}
    for stat in ["receiving_yards", "rushing_yards", "passing_yards", "receptions"]:
        if stat in original_avg and stat in adjusted_avg:
            original_val = original_avg[stat]
            adjusted_val = adjusted_avg[stat]
            if original_val > 0:
                pct_change = ((adjusted_val - original_val) / original_val) * 100
                if abs(pct_change) >= 1:  # Only track changes >= 1%
                    # Generate explanation
                    explanation = generate_adjustment_explanation(stat, pct_change, game_script_applied, reception_share, rushing_opportunity)
                    
                    adjustments[stat] = {
                        "original": round(original_val, 1),
                        "adjusted": round(adjusted_val, 1),
                        "change_pct": round(pct_change, 1),
                        "game_script": game_script_applied,
                        "explanation": explanation
                    }
    
    adjusted_stats["adjustments"] = adjustments
    return adjusted_stats

def generate_adjustment_explanation(stat, pct_change, game_script_applied, reception_share, rushing_opportunity):
    """Generate explanation for why adjustment was made"""
    if game_script_applied:
        if stat in ["receiving_yards", "receptions"]:
            if pct_change > 0:
                return "Underdog team expected to pass more in catch-up situations. Game script favors receiving stats."
            else:
                return "Favorite team likely to run more with lead. Game script reduces receiving opportunities."
        elif stat == "rushing_yards":
            if pct_change > 0:
                return "Favorite team expected to control clock with ground game. Game script boosts rushing volume."
            else:
                return "Underdog team likely to abandon run game when trailing. Game script reduces rushing attempts."
        elif stat == "passing_yards":
            if pct_change > 0:
                return "Underdog QB expected to throw more in garbage time. Game script increases passing volume."
            else:
                return "Favorite team likely to limit passing with lead. Game script reduces passing attempts."
    
    # Non-game script adjustments
    if stat in ["receiving_yards", "receptions"]:
        if reception_share > 0.20:
            return f"High target share ({reception_share:.1%}) reduces variance. More predictable performance expected."
        elif reception_share < 0.10:
            return f"Low target share ({reception_share:.1%}) increases variance. Less predictable performance expected."
    
    return "Adjustment based on opponent matchup vs league average defensive performance."

def get_opportunity_multiplier(reception_share, stat_type):
    """Get opportunity multiplier for projecting stats based on reception share"""
    if stat_type in ["receiving_yards", "receptions"]:
        if reception_share > 0.20:
            return 1.1  # High share players get slight boost
        elif reception_share < 0.10:
            return 0.9  # Low share players get slight reduction
    
    return 1.0  # No adjustment for other stats or medium shares