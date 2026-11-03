"""Volleyball results from API-Volleyball (api-sports.io, same key as API-Football).

The free plan gives whole past seasons 2022-2024 and, for the current season, only games
from yesterday to tomorrow. So history is downloaded once per league and season, and every
daily run saves those three days; the saved days build up this season's results over time.

  data/volleyball/seasons/<league>_<season>.json   one past season
  data/volleyball/days/<date>.json                 every game on one date (all leagues)
  data/volleyball/games.csv                        all finished games, one row each, set points included

Usage: python src/volley_download.py [--history] [--days]   (no flag: both)
"""
import argparse
import json
import sys
from pathlib import Path

import time

import pandas as pd
import requests

from results90 import api_key

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "volleyball"
API = "https://v1.volleyball.api-sports.io"
HISTORY_SEASONS = (2022, 2023, 2024)

# league id -> (short code, name shown on the dashboard)
LEAGUES = {
    97: ("ITA", "Italy SuperLega"), 89: ("ITA-W", "Italy Serie A1 Women"),
    113: ("POL", "Poland PlusLiga"), 120: ("POL-W", "Poland Tauron Liga Women"),
    172: ("TUR", "Turkey Efeler Ligi"), 174: ("TUR-W", "Turkey Sultanlar Ligi Women"),
    25: ("BRA", "Brazil Superliga"), 24: ("BRA-W", "Brazil Superliga Women"),
    132: ("RUS", "Russia Superleague"), 133: ("RUS-W", "Russia Superleague Women"),
    66: ("GER", "Germany Bundesliga"), 63: ("FRA", "France Ligue A"),
    252: ("JPN", "Japan SV.League"), 253: ("JPN-W", "Japan SV.League Women"),
    248: ("CL", "CEV Champions League"), 251: ("CL-W", "CEV Champions League Women"),
}


def call(path: str, **params) -> dict:
    time.sleep(6.5)   # free plan: 10 requests a minute
    for attempt in range(5):
        try:
            r = requests.get(f"{API}/{path}", params=params, headers={"x-apisports-key": api_key()}, timeout=60)
            break
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
    else:
        return {"left": None, "errors": {"network": "no connection"}}
    body = r.json()
    left = r.headers.get("x-ratelimit-requests-remaining")
    if body.get("errors"):
        print(f"  {path} {params}: {body['errors']}")
    return {"left": left, **body}


def fetch_history(force=False):
    (DIR / "seasons").mkdir(parents=True, exist_ok=True)
    for lid, (code, _) in LEAGUES.items():
        for season in HISTORY_SEASONS:
            f = DIR / "seasons" / f"{code}_{season}.json"
            if f.exists() and not force:
                continue
            body = call("games", league=lid, season=season)
            if body.get("errors"):
                continue
            f.write_text(json.dumps(body.get("response", [])))
            print(f"  {code} {season}: {body.get('results', 0)} games (requests left today {body['left']})")


def fetch_days(today: pd.Timestamp):
    """Yesterday, today and tomorrow (all the free plan allows). Re-fetched every run."""
    (DIR / "days").mkdir(parents=True, exist_ok=True)
    for d in (today - pd.Timedelta(days=1), today, today + pd.Timedelta(days=1)):
        ds = d.strftime("%Y-%m-%d")
        body = call("games", date=ds)
        if body.get("errors"):
            continue
        (DIR / "days" / f"{ds}.json").write_text(json.dumps(body.get("response", [])))
        print(f"  {ds}: {body.get('results', 0)} games, all leagues (requests left today {body['left']})")


def flatten(g: dict) -> dict:
    p = g.get("periods") or {}
    row = {
        "game_id": g["id"], "date": g["date"][:10], "time_utc": g["date"][11:16], "status": g["status"]["short"],
        "league_id": g["league"]["id"], "season": g["league"]["season"],
        "home": g["teams"]["home"]["name"], "away": g["teams"]["away"]["name"],
        "home_id": g["teams"]["home"]["id"], "away_id": g["teams"]["away"]["id"],
        "hs": g["scores"]["home"], "as": g["scores"]["away"],
    }
    for i, k in enumerate(("first", "second", "third", "fourth", "fifth"), start=1):
        s = p.get(k) or {}
        row[f"s{i}h"], row[f"s{i}a"] = s.get("home"), s.get("away")
    return row


def build_table() -> pd.DataFrame:
    """Every saved game (past seasons + saved days) of the chosen leagues, one row each."""
    games = []
    for f in sorted((DIR / "seasons").glob("*.json")) + sorted((DIR / "days").glob("*.json")):
        games += json.loads(f.read_text())
    df = pd.DataFrame([flatten(g) for g in games if g["league"]["id"] in LEAGUES])
    df = df.drop_duplicates("game_id", keep="last")   # a day file is newer than a season file
    df["league"] = df["league_id"].map(lambda i: LEAGUES[i][0])
    df = df.sort_values(["date", "time_utc", "game_id"]).reset_index(drop=True)
    df.to_csv(DIR / "games.csv", index=False)
    return df


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--days", action="store_true")
    ap.add_argument("--today", type=pd.Timestamp, default=pd.Timestamp.now().normalize())
    args = ap.parse_args()
    both = not (args.history or args.days)
    if args.history or both:
        fetch_history()
    if args.days or both:
        fetch_days(args.today)
    df = build_table()
    done = df[df["status"].isin(["FT", "AW"])]
    print(f"{len(df)} games saved, {len(done)} finished")
    print(done.groupby("league").size().to_string())


if __name__ == "__main__":
    main()
