"""90-minute results for cup and European games, from API-Football.

The Odds API's final scores can include extra time and penalties, and picks are settled on
90 minutes only. API-Football reports the 90-minute score (`score.fulltime`) separately from
extra time and penalties, so cup picks are settled from it.

One request lists every game on a date, so a run costs one request per date that still has
a pick waiting for its result (free plan: about 100 requests a day). Finished days are cached
in data/results90/ and never fetched again.

The key is read from the API_FOOTBALL_KEY environment variable or config/api_football_key.txt.
"""
import difflib
import json
import os
from pathlib import Path

import pandas as pd
import requests

from europe import CUP_LEAGUES, EURO, TeamNames, _norm

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "config" / "api_football_key.txt"
CACHE = ROOT / "data" / "results90"
API = "https://v3.football.api-sports.io"

# our division code -> (country, words in API-Football's competition name)
COMPETITION = {
    "UCL": ("World", "champions league"), "UEL": ("World", "europa league"), "UECL": ("World", "conference league"),
    "EFLC": ("England", "league cup"), "FAC": ("England", "fa cup"), "DFBP": ("Germany", "dfb pokal"),
    "CDR": ("Spain", "copa del rey"), "CIT": ("Italy", "coppa italia"), "CDF": ("France", "coupe de france"),
}
# league games too, as a fallback while football-data.co.uk hasn't published a day's results
# (leagues have no extra time; corners and cards still come from football-data.co.uk)
COMPETITION.update({
    "E0": ("England", "premier league"), "E1": ("England", "championship"), "E2": ("England", "league one"),
    "E3": ("England", "league two"), "SP1": ("Spain", "la liga"), "I1": ("Italy", "serie a"),
    "D1": ("Germany", "bundesliga"), "F1": ("France", "ligue 1"), "N1": ("Netherlands", "eredivisie"),
    "P1": ("Portugal", "primeira liga"), "B1": ("Belgium", "pro league"), "T1": ("Turkey", "super lig"),
    "G1": ("Greece", "super league"), "SC0": ("Scotland", "premiership"),
})
DONE = {"FT", "AET", "PEN"}   # finished: in 90 minutes, after extra time, after penalties


def api_key() -> str | None:
    if os.environ.get("API_FOOTBALL_KEY"):
        return os.environ["API_FOOTBALL_KEY"].strip()
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line != "PASTE_KEY_HERE":
                return line
    return None


def fixtures_on(date: str, key: str, refresh: bool = False) -> list[dict]:
    """Every game API-Football has on a date (one request), cached once all are finished."""
    path = CACHE / f"{date}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    r = requests.get(f"{API}/fixtures", params={"date": date, "timezone": "Europe/London"},
                     headers={"x-apisports-key": key}, timeout=30)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or body.get("errors"):
        raise RuntimeError(f"API-Football {date}: HTTP {r.status_code} {body.get('errors') or r.text[:200]}")
    games = body.get("response", [])
    left = r.headers.get("x-ratelimit-requests-remaining")
    print(f"  API-Football {date}: {len(games)} games listed ({left} requests left today)")
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(games), encoding="utf-8")
    return games


def _competition(game: dict, div: str) -> bool:
    country, words = COMPETITION[div]
    lg = game.get("league", {})
    name = _norm(lg.get("name", ""))
    return words in name and (country == "World" or lg.get("country") == country) and "women" not in name


def _same(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def ninety_minute_results(log: pd.DataFrame, today: pd.Timestamp, hist: pd.DataFrame, key: str,
                          days_back: int = 7) -> pd.DataFrame:
    """90-minute scores for cup and European picks still waiting for a result from the last
    `days_back` days. Returns rows shaped like the league data (Div, Date, HomeTeam, AwayTeam,
    FTHG, FTAG, HTHG, HTAG) for fill_results()."""
    if log.empty:
        return pd.DataFrame()
    t = today.strftime("%Y-%m-%d")
    since = (today - pd.Timedelta(days=days_back)).strftime("%Y-%m-%d")
    waiting = log[log["div"].isin(COMPETITION) & (log["result"] == "") & (log["date"] < t) & (log["date"] >= since)]
    rows = []
    for date, day in waiting.groupby("date"):
        try:   # the free plan only covers yesterday to tomorrow; older days come from cache or not at all
            games = fixtures_on(date, key, refresh=(date >= (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")))
        except RuntimeError as e:
            print(f"  API-Football {date}: skipped ({str(e)[-90:]})")
            continue
        if not all(g["fixture"]["status"]["short"] in DONE for g in games if any(_competition(g, d) for d in set(day["div"]))):
            (CACHE / f"{date}.json").unlink(missing_ok=True)   # some still to finish: fetch again next run
        for _, m in day.iterrows():
            names = TeamNames(hist, CUP_LEAGUES.get(m["div"]))
            best, score = None, 0.0
            for g in games:
                if not _competition(g, m["div"]):
                    continue
                h, a = g["teams"]["home"]["name"], g["teams"]["away"]["name"]
                sh = 1.0 if names(h) == m["home"] else _same(h, m["home"])
                sa = 1.0 if names(a) == m["away"] else _same(a, m["away"])
                # both names close, or one exact and the other roughly (small clubs are spelt many ways)
                ok = min(sh, sa) >= 0.7 or (max(sh, sa) >= 0.9 and min(sh, sa) >= 0.4)
                if ok and sh + sa > score:
                    best, score = g, sh + sa
            if best is None:
                continue
            ft, ht = best["score"]["fulltime"], best["score"]["halftime"]
            if best["fixture"]["status"]["short"] not in DONE or ft["home"] is None:
                continue
            rows.append({"Div": m["div"], "Date": date, "HomeTeam": m["home"], "AwayTeam": m["away"],
                         "FTHG": int(ft["home"]), "FTAG": int(ft["away"]),
                         "HTHG": ht["home"], "HTAG": ht["away"], "status": best["fixture"]["status"]["short"]})
    out = pd.DataFrame(rows)
    if len(out):
        et = (out["status"] != "FT").sum()
        print(f"  90-minute results: {len(out)} games ({et} went to extra time or penalties; settled on 90 minutes)")
    return out.drop(columns=["status"], errors="ignore")
