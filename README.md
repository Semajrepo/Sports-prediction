# Football safe picks

Predicts three picks per match for 14 European leagues and shows them on the Football Safe Picks dashboard:

1. **1X2 / Double Chance** (Result): Home, Away, Home/Draw or Away/Draw. A straight win only when it is at least 65% likely.
2. **Two extra picks** from two different markets: goals (Over/Under, GG/NG, team goals, 1st half goals), corners (total, home, away) or cards (total, home, away). Each is the safest option between 55% and 85% likely, with at most one corners and one cards pick per match.

Each pick has:
- **a probability** (its chance of winning);
- **a reason**: recent form, team averages, the referee's card rate where known, and how often that exact bet would have won in each team's last 8 matches and past meetings.

Cards count yellows and reds as one each. Every pick is settled on the **90-minute result**; extra time and penalties never count.

The dashboard shows no odds or prices. Bookmaker prices are still used behind the scenes to work out result and goal probabilities, and are kept in `output/picks_log.csv`.

## Daily update

```bash
python src/update.py
```

1. Downloads the latest results and fixtures from football-data.co.uk.
2. Retrains on every match played so far.
3. Makes picks for today and the next two days.
4. Fills in results for past picks.
5. Writes the dashboard files.

GitHub Actions runs it at 07:25, 13:00, 19:00 and 23:30 West Africa time (`.github/workflows/daily-update.yml`) and commits the new files to the repo. Only the 07:25 run uses The Odds API (500 free credits a month); the others and manual runs use `--no-europe`, keeping the morning's European picks and fetching results only. It needs the repository secrets `API_FOOTBALL_KEY` and `ODDS_API_KEY`. To update now, press "Get latest results" on the site (or open the repo's Actions tab, pick "Daily update" and press "Run workflow"), then "Reload" once it finishes.

To run it on this PC instead, double-click `daily_update.bat` (it pulls first, then commits and pushes). `setup_daily_task.ps1` schedules that .bat in Windows; use either GitHub or the Windows task, not both. Options for `update.py`:

- `--days 5` covers a longer window.
- `--today 2026-10-27 --no-download` re-runs a day from data already on disk.

The record of every pick made is `output/picks_log.csv`. A match's picks are frozen from its match day, so the record always holds the last prediction made before kickoff. Each fixture list is kept as `data/fixtures/fixtures_<date>.csv`.

football-data.co.uk usually posts each round a few days before it starts, so the window can be short on days when the next round isn't listed yet.

To pick your own games, pass a CSV with `Div,Date,HomeTeam,AwayTeam` and, if possible, the average odds columns `AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5`:

```bash
python src/predict.py --fixtures my_games.csv
```

Team names must match football-data.co.uk spelling; the script suggests the closest name when one is unknown.

## Dashboard

| Section | What it shows |
|---|---|
| Picks | Any day (calendar for earlier days; test picks shown where there were no live picks); market chips; matches grouped by competition with picks as coloured pills (chance only); a slip showing the chance all picks win |
| Results | Recent days (✓ when 70%+ of picks won); where the system works best (competitions ranked by % won and by beating its forecast, with trends, since 2019 or since Aug 2025); a competition × market type grid; every past pick with its 90-minute result, filterable, with won-vs-predicted by month |
| Performance | The backtest: hit rates, calibration, by league, by pick option |
| How it works | The method and what each label means |

Colours mark market type everywhere: Result, Goals, Corners, Cards.

History sources:

- **Live:** picks made before kickoff.
- **Back-check:** the 23–26 Oct round, generated after the games from pre-match data.
- **Test:** picks from the walk-forward backtest for Aug 2025 to 22 Oct 2026, kept until live history builds up. Rebuild them with `python src/build_test_history.py`.

## Odds sources

| Markets | Price shown |
|---|---|
| Home, Away, Over/Under 2.5 | Real bookmaker prices (average and best of several bookmakers) from football-data.co.uk |
| Home/Draw, Away/Draw | Estimated from those 1X2 prices (marked ≈) |
| Corners, cards, GG/NG, team goals | No free source; fair odds only |

- **SportyBet** has no public odds API, and its prices are usually lower than the international ones, with fewer markets on smaller games. On the dashboard, type SportyBet's price for each pick into the slip: it shows which picks are still worth taking and the slip's expected return at those prices.
- **OddsPapi** lists SportyBet prices (1X2, Over/Under, both teams to score) with a free plan of 250 requests a month; it isn't connected, and it's unclear whether its prices are SportyBet Nigeria's.
- **The Odds API** (free key) has soccer 1X2 prices for UK/EU bookmakers. Its corners and cards markets cover US bookmakers only.

## European competitions and domestic cups

Covered: Champions League, Europa League and Conference League, plus the EFL Cup, FA Cup, DFB-Pokal, Copa del Rey, Coppa Italia and Coupe de France. Cups out of season are checked for free and return no games. The Portuguese, Dutch, Belgian, Turkish, Greek and Scottish cups aren't offered by The Odds API.

football-data.co.uk doesn't cover them, so `src/europe.py` gets their fixtures, prices and results from [The Odds API](https://the-odds-api.com) (free plan: 500 credits a month). It turns on as soon as a key is saved in `config/odds_api_key.txt` (or the `ODDS_API_KEY` environment variable).

Credits are spent only when needed:

| Data | When it's fetched | Cost |
|---|---|---|
| Fixture lists | Every run | Free |
| 1X2 and Over/Under 2.5 prices | Only when a competition has a game in the window | About 2 credits per competition |
| Final scores | Only when a European pick is waiting for its result | 2 credits per competition |

A typical month uses well under 200 credits. Use `python src/update.py --no-europe` to skip it.

- **Result and goals picks** work as for the leagues, since they come from bookmaker prices.
- **Club names** are matched to football-data.co.uk names (`ALIASES` in `europe.py`), so form and reasons use each club's league history.
- **Corners and cards** aren't picked for European games yet: they need league-style history for both clubs.
- **1st-half picks** are skipped, because the free scores have no half-time result.
- **Cup and European results** come from [API-Football](https://www.api-football.com) (`src/results90.py`, key in `config/api_football_key.txt`, free plan about 100 requests a day). Its `score.fulltime` is the 90-minute score, reported separately from extra time and penalties, so every pick is settled on 90 minutes. One request covers every game on a date; finished days are cached in `data/results90/`. The Odds API's final scores are used only for European league-phase games (September to January), which can't go to extra time. Use `--no-results90` to skip it.
- **Games already under way** are never given picks.

`python tools/test_europe_sample.py` checks the whole path offline with sample data.

## Backtesting

```bash
python src/backtest.py --refit        # about 25 minutes
python src/validate_reasons.py        # about 20 minutes
python src/build_test_history.py
```

Backtest results, Jul 2019 to Oct 2026, 37,010 matches:

| Pick | Predicted | Won |
|---|---|---|
| Pick 1 (1X2 / Double Chance) | 73.5% | 75.2% |
| Pick 2 | 84.0% | 84.6% |
| Pick 3 | 82.7% | 83.2% |
| All three in one match | 51.1% if independent | 53.4% |

- Goal probabilities come from bookmaker odds, which beat the team ratings on their own.
- Corners and cards have no odds in the data. Their team ratings overfit at first, so each season they are pulled toward the league average by an amount measured on earlier seasons. Calibrated this way they beat a league-average guess and land at their stated rate.
- The "history agrees / split" label did not change how often picks won at the same probability. Trust the percentage; the reasons are context.
- Pick 1 lost about 3.6% per bet at average bookmaker odds: "safe" means likely to win, not profitable.

## Files

| File | What it does |
|---|---|
| `src/update.py` | The daily update (download, retrain, predict, fill in results, export) |
| `src/download.py` | Downloads 2015/16 to now for all leagues into `data/matches.parquet` |
| `src/model.py` | Expected goals from team ratings and from bookmaker odds; Dixon-Coles score matrix; corners and cards ratings |
| `src/markets.py` | SportyBet-style markets, settlement and pick rules (thresholds at the top) |
| `src/predict.py` | Picks and bookmaker prices for a fixture list; `predict_fixtures()` is shared with the daily update |
| `src/reasons.py` | The reason text and "history agrees / split" label for each pick |
| `src/export_dashboard.py` | Writes the dashboard files from the record and the backtest |
| `src/backtest.py` | Walk-forward backtest, writes `output/backtest_summary.json` |
| `src/validate_reasons.py` | Tests whether the history label predicts results beyond the probability |
| `src/build_test_history.py` | Test picks for the History page |
| `src/europe.py` | Champions, Europa and Conference League and domestic cups from The Odds API |
| `src/results90.py` | 90-minute results for cup and European games from API-Football |
| `src/build_league_trends.py` | Long-run results per league, season and market type for the Results page |

## Volleyball

Same dashboard, switched with the Football / Volleyball buttons in the header.

- **Data:** API-Volleyball (api-sports.io), same key as API-Football (`config/api_football_key.txt`). The free plan gives whole seasons 2022-2024 and, for now, only yesterday to tomorrow (10 requests a minute, 100 a day). `src/volley_download.py` saves past seasons once (`data/volleyball/seasons/`) and every day's games (`data/volleyball/days/`), so this season builds up day by day. `data/volleyball/games.csv` holds them all.
- **Leagues:** Italy, Poland, Turkey, Brazil, Russia, Japan (men and women), Germany and France (men), CEV Champions League (men; women from 2026).
- **Model** (`src/volley_model.py`): rally-level team ratings (points won/lost, 180-day half-life, a league level plus team level), then the exact chance of winning a set to 25 (5th to 15), then every set score. Calibrated with `shrink` and `spread` on 2023/24 (`src/volley_backtest.py`, walk-forward weekly from Sep 2023).
- **Markets:** winner, set handicap ±1.5/±2.5, total sets O/U 3.5 and 4.5, 1st-set winner. Best pick = safest between 55% and 79%; none when either team has fewer than 3 games in the data.
- **Backtest, 2024/25 season (unseen):** 2,869 best picks, predicted 73.1%, won 72.9%.
- **Daily:** `src/update.py` calls `src/volley_update.py` at the end (skip with `--no-volleyball`). It writes `output/volley_log.csv` and `output/dashboard/volley_*.csv`. Rebuild the backtest with `python src/volley_backtest.py --refit`.

## Viewing the dashboard

Double-click `view_dashboard.bat` (or run `python -m http.server 8765` here and open http://localhost:8765/output/dashboard/view.html). The page (`output/dashboard/index.html`) reads the CSV files in `output/dashboard/`, so it is as current as the last update run. `view.html` supplies the page's theme and `dash-shim.js` loads the CSVs.

SportyBet booking codes are no longer booked automatically; `output/dashboard/codes.csv` keeps the ones booked earlier. `.claude/skills/sportybet-code` and `src/slip.py` are the old Claude-driven booking flow, kept for reference.

## API keys

`config/api_football_key.txt` and `config/odds_api_key.txt` are not in git (see `.gitignore`). On a new machine, create them again or set the `API_FOOTBALL_KEY` and `ODDS_API_KEY` environment variables.

## Online

GitHub Pages serves the repo at https://semajrepo.github.io/Sports-prediction/ (the root `index.html` opens the dashboard). Each daily update commit republishes it within a few minutes.
