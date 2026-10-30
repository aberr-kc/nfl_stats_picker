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
