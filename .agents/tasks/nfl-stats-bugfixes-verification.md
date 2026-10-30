# Verification log: scraper fix (Part A) + math bug fixes 1-8

Python: `c:\code\nfl_stats_project-master\.venv\Scripts\python.exe`. Throwaway check scripts live in `%TEMP%\nflbug\` (not in the repo).

## 0. Preflight

- Branch `math-bugfixes`, tree clean apart from untracked `.agents/tasks/*` notes.
- SHA256 of `nfl_stats.db` = `125d7846...df645c6`, identical to `nfl_stats.backup-20261030-111454.db`, so the existing backup covers the state before any write.
- The user's own `run_local.py` server was already listening on 127.0.0.1:8000 (PID 36300). It was left alone; verification servers in this step use port 8001.
- Baseline on a DB copy (`%TEMP%\nflbug\baseline`, `run_picks.py`), NFL_SEASON=2026 NFL_WEEK=8: 6 players, 45 rows. Josh Jacobs `rushing_yards` player_value 12.0, line 60.5 SportsBet, probabilityUnder 91.7 (5 bookmaker rows, 91.6-92.1).

## Teams table + migrations

- `teams.py`: 32 unique values per column; every distinct non-NULL `player_weekly_stats.team` is in `ALL_ABBRS`; every distinct `odds.event_name` parses; `find_opponent('NE','New York Giants vs Minnesota Vikings') is None`, `find_opponent('KC','Chicago Bears vs Green Bay Packers') is None`, `find_opponent('GB','Green Bay Packers vs Carolina Panthers') == 'CAR'`.
- `import models` run twice on the real DB: `gp` in `player_weekly_stats`, `outcome` in `odds`; odds 4,413 rows and player_weekly_stats 54,537 rows before and after; 0 rows with non-NULL outcome.

## Item 2: gp (games played) stored and backfilled

Used Sleeper's `gp` field, not the all-zero rule. Sleeper weekly stats carry `gp` only for players who played (a DNP player has no `gp` key, while `gms_active` can still be 1, so it was not used). An all-zero row can also be a real 0-catch game, which `gp` distinguishes: e.g. Jayden Reed 2025 week 2 is `gp=1` with 0 receptions (injured in-game), weeks 3-13 are `gp=0`.

- `fetch_stats.py` now keeps `gp` (missing key -> 0 via the existing fillna). `$py -c "from fetch_stats import fetch_weekly_stats_sleeper as f; d=f(2026,7); print(d['gp'].describe())"`: count 2095, mean 0.653, min 0, max 1 (fetch only, no DB write).
- `save_to_db.py` already imports `models`, so the migration runs before `to_sql` appends rows with `gp`; no change needed.
- `$py backfill_gp.py` (UPDATE only, no re-insert): 24 weeks, 38 s. Example lines: `2025 wk16: 2468 players updated, 1567 with gp > 0`, `2026 wk7: 2095 players updated, 1368 with gp > 0`.
- `check_gp.py`: 0 rows with NULL gp for 2025/2026 regular; Josh Jacobs (5850) 2026 gp = 0 for weeks 1-6 and 1 for week 7 (36 rush yds); 0 rows with gp=0 and non-zero yards/receptions; total rows unchanged at 54,537.

## Part A: scraper (team_stats.py) and team_stats_data.json

- Rewritten to read 6 TeamRankings per-stat pages (`rushing-yards-per-game`, `passing-yards-per-game`, `opponent-rushing-yards-per-game`, `opponent-passing-yards-per-game`, `completions-per-game`, `opponent-completions-per-game`), each verified live: HTTP 200 with no redirect, one `table.tr-table`, 32 rows, headers `Rank, Team, 2026, Last 3, Last 1, Home, Away, 2025`. The value column is found by the header equal to the season year. TeamRankings names map through the exact table in `teams.py`.
- `verify=False` and the urllib3 warning suppression are gone. User-Agent set, 20 s timeout, 2 s between requests, 6 requests per run. Fake sample-number fallback deleted; missing team -> `{}`; league averages -> `None` when no data.
- `$py team_stats.py`: `Saved 32 teams for 2026 (data as of 2026-10-29)`. File now `{"season": 2026, "data_as_of": "2026-10-29", "scraped_at": "2026-10-30T01:51:12+00:00", "source": ..., "teams": {...}}`.
- `check_team_stats.py`: 32 teams x 6 keys, all floats. Samples: CHI rush_yards_game 154.3, JAX opp_rush_yards_game 72.2, SEA opp_pass_yards_game 144.4, MIN opp_completions_game 16.0, LAR completions_game 27.0. League defensive averages: opp rush 111.4, opp pass 221.5, opp completions 21.5.
- Failure path (`--failpath`): `update_all_team_stats(season=1999)` logged `no '1999' column (headers: [...])` and returned None; a run with a bogus slug logged `bogus-stat-page-xyz returned HTTP 307` and returned None; file SHA256 unchanged after both.

## Item 5: matchup factor (display only)

- `MATCHUP_BETA` = 0.3 for passing yards, receiving yards and receptions, 0.0 for rushing (comment cites math review S4 / rec #15). Receptions use `opp_completions_game`.
- Checks: rushing vs CIN factor 1.0 ("rushing matchup adjustment disabled (beta=0)"); receptions vs JAX use completions (23.3 vs 21.5, raw 1.0837 -> 1.0251); passing vs DET (max opp pass yds) factor 1.0952 = 1 + 0.3 x (1.3174 - 1) within 1e-9; season 2025 -> "team stats are for 2026, not 2025 (no adjustment)", factor 1.0 for every stat; unknown opponent XXX -> 1.0.

## Item 4 (ingestion): outcome saved and part of the upsert key

- `odds_api.save_odds(..., outcome=None)`; `outcome` is in the `filter_by` upsert key and in new rows; both the player-prop and the spreads/totals branches pass `outcome.get("name")`. The week-delete step is unchanged. The Odds API was not called.
- `check_odds_save.py` on `%TEMP%\nflbug\oddstest` (requests.get patched to raise, `call_odds_api` patched with canned JSON, `fetch_and_store_odds(days_ahead=4, season=2099, week=1)` run twice): both runs gave 3 rows `('player_anytime_td','Yes',None,2.1), ('player_reception_yds','Over',55.5,1.87), ('player_reception_yds','Under',55.5,1.95)`. A direct `save_odds(... outcome="Over")` upsert updated only the Over row (Under kept 1.95). Real DB odds count 4,413 before and after.

## Items 1, 2, 7: stats by player_id, no look-ahead, regular season, games played only

- `get_recent_3_game_stats_by_id`: `week < :current_week AND season_type = 'regular' AND (gp > 0 OR (gp IS NULL AND any stat <> 0))`, keyed on `player_id`. `get_recent_3_game_stats(name)` stays as a wrapper (resolves the name first) for the qb/target-share/debug scripts.
- Item 1 audit: `get_recent_3_game_stats` was the only recent-games query with a target-week bound. `app.py` `/stats/recent_average` and `/stats/recent_3_average` have no target week (they show the latest games in the lookup panel); checked, not changed.
- `check_items.py` (cwd `%TEMP%\nflbug\run`, DB copy taken after the backfill):
  - (a) `get_recent_3_game_stats_by_id(2026, '5850', 8)` -> 1 row, week 7, gp 1, rushing 36.0.
  - (b) 2025 wk16 `Michael Carter` -> 7607 (the RB); 2026 wk8 `DeVonta Smith` -> 7525 (WR, not the CB 13977), `Justin Jefferson` -> 6794. Names whose ids all lack offensive stats (defenders such as Brandon Johnson, Byron Young, Marcus Harris) are skipped and logged to stderr: `Ambiguous player name skipped: Byron Young -> ['10917', '10925']`.
  - (c) 2025 week 16 windows: Josh Allen, Derrick Henry, Puka Nacua, Jalen Hurts weeks [15, 14, 13]; Parker Washington [15, 13, 12]. No week >= 16.
  - (d) Jayden Reed before 2025 wk15: weeks [14, 2, 1], all gp = 1 (the gp = 0 weeks 3-13 are skipped).
- Team lookup by id/season: `get_player_team(conn, '5850', 2026)` -> GB.

## Items 5, 6 wiring and display-only proof

- `get_player_team` (player_id + season, latest week) replaces the three name-based `LIMIT 1` lookups; `teams.find_opponent` replaces the inline dicts and substring matching; one `compute_adjustments` helper (using `team_stats.build_adjustment`) serves the web and CLI paths. `passing_tds` stays unadjusted.
- 2026 wk8 copy run (`run_picks.py`, NFL_SEASON=2026 NFL_WEEK=8): 6 players, 55 rows, 0 duplicate (player, stat, bookmaker) rows. rushing_yards: 10 rows, all changePct 0.0 ("rushing matchup adjustment disabled (beta=0)"). Pass/rec/receptions changePct values -3.5, -1.8, 1.5; recomputed `0.3 x (raw - 1)` from the JSON: 0 mismatches; receptions cite "completions allowed/game". Example: Jalen Coker receiving_yards 41.3 -> 40.6 (-1.8%), "vs GB defense (208.0 vs 221.5 league avg pass yds allowed/game, scaled x0.3)".
- Same run with `team_stats.get_matchup_factor` forced to 1.0 (`--neutral`): identical (player, stat, bookmaker) keys and identical probabilityOver/probabilityUnder/threshold_rule/player_value. The matchup factor does not reach the flag rule or the probability.
- 2025 wk16 copy run: 209 rows with adjustmentDetails, all changePct 0.0; 153 say "team stats are for 2026, not 2025 (no adjustment)", 56 are rushing (beta=0).

## Items 4 (read side) and 8 (outlier lines)

- `get_odds_for_player` selects `price, outcome`. `collapse_odds` groups rows into one entry per (market, bookmaker, line) with `prices`; flagged rows carry `prices` and `pickPrice`. Synthetic check: A Over 1.87/Under 1.95, B Over/Under 1.90 + a legacy NULL row (ignored), C legacy only -> 3 entries, 3 flagged rows (one per bookmaker, not two), pickPrice 1.87 / 1.90 / None. The real 2026 wk8 rows are all legacy (`{"unknown": price}`, pickPrice None) until the odds are re-fetched; no fetch was made.
- `drop_outlier_lines` runs at evaluation time (DB untouched), median per player/market/week across bookmakers, drop if > 25%. Drops go to stderr; single-line markets are kept and logged at DEBUG as "not checkable".
- 2025 wk16 run, drops logged: Derrick Henry player_reception_yds TAB 5.5 (median 9.5); Cooper Kupp player_receptions SportsBet 3.5 (median 2.5); Dallas Goedert player_receptions Ladbrokes 4.5 (median 3.5); Gardner Minshew and Marcus Mariota player_pass_tds SportsBet/TAB 1.5 (median 0.5); Matthew Stafford player_rush_attempts Ladbrokes 1.5 and TAB 0.5 (median 1.0). Half-unit differences on small counts exceed 25%, as the plan's known gaps said.
- (i) Parker Washington was NOT dropped. The DB has one bookmaker for his 2025 wk16 player_reception_yds: `[('Ladbrokes', 20.5, 1.88, None)]`, so the median is 20.5 itself. Log: `Outlier check not checkable (single line): Parker Washington player_reception_yds Ladbrokes 20.5 (wk 16 2025)`. The brief's "median about 60+" does not match the data; his 3-game average (74.7) is about 60, not a bookmaker median. He is still flagged Over at 20.5. 102 of 448 player-market groups that week are single-book.
- (ii) 15+ yard spreads in 2025 wk16 (all player_pass_yds): Rodgers 217.5-234.5 (median 230.5, max dev 5.6%), Brissett 240.5-260.5 (246.5, 5.7%), Burrow 255.5-270.5 (258.5, 4.6%), Josh Allen 200.5-215.5 (212.0, 5.4%), Cousins 224.5-240.5 (227.5, 5.7%), Stafford 222.5-240.5 (229.0, 5.0%), Shough 200.5-215.5 (208.0, 3.6%). None exceeds 25%; none was dropped.

## 2025 week 16 back-test (sanity check, DB copy)

Graded against actual week-16 stats for the resolved player_id (median flagged line per pick; a pick is void when the player has no gp > 0 week-16 row).

| Run | Rows | Unique picks (player, stat, side) | Hit rate |
|---|---|---|---|
| Before (leaky `<=`, baseline copy) | 305 | 90 (62 Over / 28 Under) | 75/89 = 84.3% |
| After all fixes | 248 | 76 (54 Over / 22 Under) | 37/75 = 49.3% (rows: 133/247 = 53.8%) |
| Math review honest baseline | 324 | 90 | 42/90 = 46.7% |

After: Over 27/54, Under 10/21. Break-even at the stored prices is about 53%, so this is consistent with the review: no edge, just no leakage.
