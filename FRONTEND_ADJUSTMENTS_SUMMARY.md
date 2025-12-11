# Frontend Adjustment Display Summary

## What's Now Visible on the Frontend

### Adjustment Column Added
- **New "Adjustments" column** in the Generated Picks table
- Shows percentage boosts/reductions with visual indicators
- Identifies game script vs other adjustments

### Display Format Examples:

**Kyle Pitts (receiving_yards):**
- Original: 30.0 yards
- Adjusted: 27.2 yards  
- Display: `-9.2% (GS)` in red text
- Meaning: 9.2% reduction due to Game Script

**Joe Flacco (passing_yards):**
- Original: 297.3 yards
- Adjusted: 300.8 yards
- Display: `+1.2% (GS)` in green text  
- Meaning: 1.2% boost due to Game Script

**Justice Hill (receptions):**
- Original: 1.0 receptions
- Adjusted: 0.9 receptions
- Display: `-10.0% (GS)` in red text
- Meaning: 10% reduction due to Game Script

### Visual Indicators:
- **Green (+X%)**: Positive adjustments (boosts)
- **Red (-X%)**: Negative adjustments (reductions)  
- **(GS)**: Game Script adjustment applied
- **Bold text**: Makes adjustments stand out

### What Adjustments Show:
1. **Game Script Impact**: Spread-based receiving/rushing adjustments
2. **Opportunity Impact**: Reception share variance adjustments
3. **Matchup Impact**: Opponent defense vs league average

### User Benefits:
- **Transparency**: See exactly how projections are adjusted
- **Context**: Understand why a player is flagged despite lower raw stats
- **Confidence**: Game script boosts indicate higher-probability plays
- **Strategy**: Avoid players with significant reductions

## Example Frontend Display:
```
Player: Kyle Pitts - New Orleans Saints vs Atlanta Falcons

Stat          | Player Avg | Adjusted | Adjustments | Line | Difference | Probability
receiving_yards|    30.0   |   27.2   |  -9.2% (GS) | 55.5 |   -28.3   | 4.2% Over
```

The adjustment system is now fully integrated and visible to users, providing complete transparency into how projections are calculated.