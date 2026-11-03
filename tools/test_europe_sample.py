"""Offline check of the European path with sample data shaped like The Odds API's responses.
No API calls are made. Usage: python tools/test_europe_sample.py"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")
from backtest import REPORT, add_count_inputs  # noqa: E402
from europe import TeamNames, to_fixtures  # noqa: E402
from model import MarketInverter  # noqa: E402
from predict import predict_fixtures  # noqa: E402
from update import fill_results, to_log_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
inv = MarketInverter()
hist = add_count_inputs(pd.read_parquet(ROOT / "data" / "matches.parquet").dropna(subset=["Date"]), inv)
names = TeamNames(hist)

print("Name matching:")
for n in ["Arsenal", "Atlético Madrid", "Bayern Munich", "Paris Saint Germain", "Inter Milan", "Sporting Lisbon",
          "Club Brugge", "PSV Eindhoven", "Borussia Dortmund", "Kairat Almaty", "Bodø/Glimt", "Olympiacos"]:
    print(f"  {n:22s} -> {names(n)}")


def book(key, h, d, a, o, u):
    return {"key": key, "title": key, "markets": [
        {"key": "h2h", "outcomes": [{"name": "HOME", "price": h}, {"name": "AWAY", "price": a}, {"name": "Draw", "price": d}]},
        {"key": "totals", "outcomes": [{"name": "Over", "price": o, "point": 2.5}, {"name": "Under", "price": u, "point": 2.5}]}]}


def event(i, home, away, prices):
    bms = []
    for k, p in zip(["pinnacle", "unibet_eu", "betfair_ex_eu"], prices):
        b = book(k, *p)
        for o in b["markets"][0]["outcomes"]:
            o["name"] = {"HOME": home, "AWAY": away}.get(o["name"], o["name"])
        bms.append(b)
    return {"id": f"sample{i}", "sport_key": "soccer_uefa_champs_league", "commence_time": "2026-10-28T20:00:00Z",
            "home_team": home, "away_team": away, "bookmakers": bms}


sample = [
    event(1, "Arsenal", "Atlético Madrid", [(1.80, 3.80, 4.60, 1.95, 1.90), (1.78, 3.70, 4.50, 1.92, 1.88), (1.83, 3.85, 4.70, 1.97, 1.93)]),
    event(2, "Bayern Munich", "Club Brugge", [(1.22, 7.00, 11.0, 1.40, 3.00), (1.20, 6.80, 10.5, 1.38, 2.90), (1.23, 7.20, 12.0, 1.42, 3.05)]),
    event(3, "Kairat Almaty", "Inter Milan", [(7.50, 4.80, 1.40, 1.75, 2.05), (7.20, 4.60, 1.42, 1.73, 2.02), (8.00, 5.00, 1.39, 1.78, 2.08)]),
]
fx = to_fixtures(sample, "UCL", names)
print("\nFixtures built:", fx[["Div", "Date", "Time", "HomeTeam", "AwayTeam", "AvgH", "AvgD", "AvgA", "Avg>2.5", "MaxH"]].to_string(index=False))

cfg = json.loads(REPORT.read_text())
rows = predict_fixtures(fx, hist, pd.Timestamp("2026-10-27"), cfg, inv)
for r in rows:
    print(f"\n{r['league']}: {r['home']} v {r['away']}  (H {r['p_home']:.0%} D {r['p_draw']:.0%} A {r['p_away']:.0%})")
    for p in r["picks"]:
        books = f" books {p['book_avg']} best {p['book_best']}" if p.get("book_avg") else ""
        print(f"  {p['category']:<22} {p['pick']:<22} {p['prob']:.0%} fair {p['fair_odds']}{books}\n      {p['why']}")

log = to_log_rows(rows, "2026-10-27")
extra = pd.DataFrame([{"Div": "UCL", "Date": "2026-10-28", "HomeTeam": names("Arsenal"), "AwayTeam": names("Atlético Madrid"), "FTHG": 2, "FTAG": 1}])
n = fill_results(log, hist, extra)
print(f"\nSettled {n} sample match(es):",
      log.loc[log["result"] != "", ["home", "away", "result", "pick1", "pick1_won", "pick2", "pick2_won", "pick3", "pick3_won"]].to_string(index=False))
