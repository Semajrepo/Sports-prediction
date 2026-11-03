"""Daily volleyball update: save the last/next days' games, retrain, pick, settle, write dashboard files.

The free API plan lists games from yesterday to tomorrow only, so picks cover today and
tomorrow. A game's picks are frozen on its match day, like football's.

  output/volley_log.csv                      every live pick, with its result once played
  output/dashboard/volley_upcoming.csv       today and tomorrow, same columns as upcoming.csv
  output/dashboard/volley_history.csv        past picks: live + test picks from the backtest
  output/dashboard/volley_status.csv         when it ran and what the window covers
  output/dashboard/volley_league_seasons.csv results per league and season (backtest)
  output/dashboard/volley_*.csv              backtest tables for the Performance tab

Usage: python src/volley_update.py [--today 2026-10-28] [--no-download]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from export_dashboard import OUT, match_id
from volley_backtest import BEST_MAX, CALIB_END, REPORT, best_pick
from volley_download import DIR, LEAGUES, build_table, fetch_days
from volley_model import KEY_INFO, Ratings, finished, market_probs, settle

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "output" / "volley_log.csv"
NAME = {code: name for code, name in LEAGUES.values()}
FAMILY = {"Winner": "Result", "1st Set Winner": "Result", "Set Handicap": "Sets", "Total Sets": "Sets"}
SOURCE = {"before kickoff": "Live", "back-check": "Back-check"}


def uk_time(date: str, time_utc: str) -> tuple[str, str]:
    """Kick-off in UK time, as football's times are."""
    t = pd.Timestamp(f"{date} {time_utc}", tz="UTC").tz_convert("Europe/London")
    return t.strftime("%Y-%m-%d"), t.strftime("%H:%M")


def form(g: pd.DataFrame, team_id, n=5) -> str:
    """Last n results of a team, W/L, latest last."""
    t = g[(g["home_id"] == team_id) | (g["away_id"] == team_id)].tail(n)
    return "".join("W" if (r.home_id == team_id) == (r.hs > r["as"]) else "L" for _, r in t.iterrows()) or "n/a"


def why(m, g: pd.DataFrame, q: float, probs: pd.Series, seen: int) -> str:
    fav, p = (m["home"], probs["1"]) if probs["1"] >= 0.5 else (m["away"], probs["2"])
    rally = q if fav == m["home"] else 1 - q
    meet = g[((g["home_id"] == m["home_id"]) & (g["away_id"] == m["away_id"])) | ((g["home_id"] == m["away_id"]) & (g["away_id"] == m["home_id"]))].tail(4)
    h2h = (f"Last {len(meet)} meetings: " + ", ".join(f"{r.home} {int(r.hs)}-{int(r['as'])}" for _, r in meet.iterrows()) + "."
           if len(meet) else "No meetings in the data since 2022.")
    note = " Few recent games for one side, so this is rougher than usual." if seen < 10 else ""
    return (f"Form: {m['home']} {form(g, m['home_id'])}, {m['away']} {form(g, m['away_id'])} (latest last). "
            f"Ratings give {fav} {rally:.0%} of rallies, so {p:.0%} to win; goes to 5 sets {probs['O4.5']:.0%}. {h2h}{note}")


def picks_for(p: pd.Series) -> list[str]:
    """Best pick (safest up to 79%), then the winner and the likelier total-sets side as 'more picks'."""
    b, _ = best_pick(p, BEST_MAX)
    win = "1" if p["1"] >= p["2"] else "2"
    sets = "O3.5" if p["O3.5"] >= p["U3.5"] else "U3.5"
    return [b] + [k for k in (win, sets) if k != b]   # b None: no best pick, only the others


def predict(games: pd.DataFrame, todo: pd.DataFrame, today: pd.Timestamp, cal: dict, made: str) -> pd.DataFrame:
    """Picks for the games in `todo`, from ratings fitted on all `games` before `today`."""
    g = finished(games)
    g = g[g["date"] < today.strftime("%Y-%m-%d")]
    r = Ratings().fit(g, today)   # games before this day only
    up = todo[todo["status"].isin(["NS", "TBD"])] if made == "before kickoff" else todo
    rows = []
    for _, m in up.iterrows():
        d, t = uk_time(m["date"], m["time_utc"])
        q = r.rally_prob(m["home_id"], m["away_id"], m["league"])
        p = market_probs([q], cal["shrink"], cal["spread"]).iloc[0]
        seen = min(r.games_seen.get(m["home_id"], 0), r.games_seen.get(m["away_id"], 0))
        row = {"match_id": "V-" + match_id(d, m["home"], m["away"]), "game_id": str(m["game_id"]), "made": made,
               "made_on": today.strftime("%Y-%m-%d"), "date": d, "time": t, "league": NAME[m["league"]], "div": m["league"],
               "home": m["home"], "away": m["away"], "result": "", "p_home": round(float(p["1"]), 3), "p_draw": "",
               "p_away": round(float(p["2"]), 3), "seen": seen}
        reason = why(m, g, q, p, seen)
        ks = picks_for(p)
        if seen < 3:   # a side we know nothing about: no best pick, the others stay as context
            ks[0] = None
        for i, k in enumerate(ks):
            if k is None:
                continue
            cat, label = KEY_INFO[k]
            row.update({f"pick{i}_key": k, f"pick{i}_market": cat, f"pick{i}": label, f"pick{i}_prob": round(float(p[k]), 3),
                        f"pick{i}_won": "", f"pick{i}_why": reason, f"pick{i}_support": "Little history" if seen < 10 else "Rated on recent games",
                        f"pick{i}_family": FAMILY[cat]})
        rows.append(row)
    return pd.DataFrame(rows).astype(str) if rows else pd.DataFrame()


def merge(log: pd.DataFrame, new: pd.DataFrame, today: str) -> pd.DataFrame:
    if log.empty:
        return new
    if new.empty:
        return log
    frozen = set(log.loc[log["date"] <= today, "match_id"])
    new = new[~new["match_id"].isin(frozen)]
    out = pd.concat([log[~log["match_id"].isin(new["match_id"])], new], ignore_index=True)
    return out.fillna("").sort_values(["date", "time", "league", "home"]).reset_index(drop=True)


def fill_results(log: pd.DataFrame, games: pd.DataFrame) -> int:
    g = finished(games).assign(game_id=lambda d: d["game_id"].astype(str)).set_index("game_id")
    won = settle(g)
    n = 0
    for idx, m in log[log["result"] == ""].iterrows():
        if m["game_id"] not in g.index:
            continue
        r = g.loc[m["game_id"]]
        log.at[idx, "result"] = f"{int(r['hs'])}-{int(r['as'])}"
        for i in (0, 1, 2):
            k = m.get(f"pick{i}_key", "")
            if k:
                w = won.at[m["game_id"], k]
                log.at[idx, f"pick{i}_won"] = "" if np.isnan(w) else ("won" if w == 1 else "lost")
        n += 1
    # cancelled or postponed: drop the open picks so they don't sit as pending forever
    gone = set(games.loc[games["status"].isin(["CANC", "POST", "WO", "AW"]), "game_id"].astype(str))
    drop = log["game_id"].isin(gone) & (log["result"] == "")
    log.drop(log.index[drop], inplace=True)
    return n


def test_history(cal: dict) -> pd.DataFrame:
    """Best picks from the backtest's test period (2024/25 season), in history.csv's columns."""
    bt = pd.read_parquet(DIR / "backtest_picks.parquet")
    bt = bt[(pd.to_datetime(bt["date"]) >= CALIB_END) & bt["pick"].notna()]
    rows = []
    for _, m in bt.iterrows():
        d, _ = uk_time(m["date"], m["time_utc"])
        mid = "V-" + match_id(d, m["home"], m["away"])
        cat, label = KEY_INFO[m["pick"]]
        rows.append({"pick_id": f"{mid}|0", "match_id": mid, "date": d, "competition": NAME[m["league"]], "home": m["home"],
                     "away": m["away"], "result": f"{int(m['hs'])}-{int(m['as'])}", "slot": "Best", "family": FAMILY[cat],
                     "market": cat, "pick": label, "prob": round(float(m["p"]), 3),
                     "outcome": "won" if m["won"] == 1 else "lost", "source": "Test"})
    return pd.DataFrame(rows)


def flat(log: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, m in log.iterrows():
        for i in (0, 1, 2):
            if not m.get(f"pick{i}"):
                continue
            w = m.get(f"pick{i}_won", "")
            rows.append({"pick_id": f"{m['match_id']}|{i}", "match_id": m["match_id"], "date": m["date"], "competition": m["league"],
                         "home": m["home"], "away": m["away"], "result": m["result"], "slot": "Best" if i == 0 else f"Pick {i}",
                         "family": m[f"pick{i}_family"], "market": m[f"pick{i}_market"], "pick": m[f"pick{i}"],
                         "prob": m[f"pick{i}_prob"], "outcome": w if w in ("won", "lost") else "pending",
                         "source": SOURCE.get(m["made"], m["made"])})
    return pd.DataFrame(rows)


def write_dashboard(log: pd.DataFrame, today: pd.Timestamp, cal: dict, data_through: str):
    t0, t1 = today.strftime("%Y-%m-%d"), (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    up = log[(log["date"] >= t0) & (log["date"] <= t1)]
    up.drop(columns=["game_id", "seen"], errors="ignore").to_csv(OUT / "volley_upcoming.csv", index=False)
    live = flat(log[log["date"] < t0]) if len(log) else pd.DataFrame()
    hist = pd.concat([live, test_history(cal)], ignore_index=True)
    hist = hist.sort_values(["date", "competition", "home", "slot"], ascending=[False, True, True, True])
    hist.to_csv(OUT / "volley_history.csv", index=False)
    pd.DataFrame([{"updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "data_through": data_through,
                   "window_from": t0, "window_to": t1, "days": 2, "upcoming_matches": len(up),
                   "live_picks": int((hist["source"] != "Test").sum()), "test_picks": int((hist["source"] == "Test").sum())}]
                 ).to_csv(OUT / "volley_status.csv", index=False)


def write_performance(rep: dict):
    """Backtest tables (2024/25 season, never used for calibration) and per-league/season results."""
    pd.DataFrame([{"slot": "best", "n": rep["best_pick"]["n"], "predicted": rep["best_pick"]["pred"], "hit_rate": rep["best_pick"]["hit"]}]
                 ).to_csv(OUT / "volley_backtest_best.csv", index=False)
    rel = pd.DataFrame(rep["best_reliability"]).rename(columns={"pred": "predicted", "hit": "hit_rate"})
    rel["band"] = rel["band"].map(lambda b: "–".join(f"{float(x) * 100:.0f}" for x in b.strip("(]").split(", ")) + "%")
    rel.to_csv(OUT / "volley_reliability.csv", index=False)
    mk = pd.DataFrame(rep["by_market"]).rename(columns={"label": "option", "pred": "predicted", "hit": "hit_rate"})
    best = {r["pick"]: r["n"] for r in rep["best_by_market"]}
    mk["family"] = mk["category"].map(FAMILY)
    mk["n"] = mk["key"].map(best).fillna(0).astype(int)   # times it was the best pick
    mk[["family", "category", "option", "n", "predicted", "hit_rate"]].to_csv(OUT / "volley_markets.csv", index=False)
    lg = pd.DataFrame(rep["best_by_league"]).rename(columns={"pred": "predicted", "hit": "hit_rate"})
    lg["league"] = lg["league"].map(NAME)
    lg[["league", "n", "predicted", "hit_rate"]].to_csv(OUT / "volley_leagues.csv", index=False)

    bt = pd.read_parquet(DIR / "backtest_picks.parquet").dropna(subset=["won"])
    bt = bt.assign(family=bt["pick"].map(lambda k: FAMILY[KEY_INFO[k][0]]), league=bt["league"].map(NAME),
                   season=bt["season"].map(lambda y: f"{y}/{str(y + 1)[2:]}"), slot="Best")
    out = bt.groupby(["slot", "league", "season", "family"]).agg(n=("won", "size"), won=("won", "sum"), predicted=("p", "mean")).reset_index()
    out["won"] = out["won"].astype(int)
    out["predicted"] = out["predicted"].round(4)
    out.to_csv(OUT / "volley_league_seasons.csv", index=False)


def run(today: pd.Timestamp, download=True):
    t = today.strftime("%Y-%m-%d")
    if download:
        fetch_days(today)
    games = build_table()
    rep = json.loads(REPORT.read_text())
    cal = rep["calibration"]
    day_games = games[games["date"] >= (today - pd.Timedelta(days=1)).strftime("%Y-%m-%d")]
    new = predict(games, day_games[day_games["date"] >= t], today, cal, "before kickoff")
    log = pd.read_csv(LOG, dtype=str, keep_default_na=False) if LOG.exists() else pd.DataFrame()
    if log.empty:   # first run: yesterday's games as a back-check from the ratings before them
        yday = today - pd.Timedelta(days=1)
        new = pd.concat([predict(games, day_games[day_games["date"] == yday.strftime("%Y-%m-%d")], yday, cal, "back-check"), new], ignore_index=True)
    log = merge(log, new, t).fillna("")
    settled = fill_results(log, games) if len(log) else 0
    LOG.parent.mkdir(exist_ok=True)
    log.to_csv(LOG, index=False)
    done = finished(games)
    print(f"Volleyball: {len(new)} games picked, {settled} newly settled, record {len(log)} games")
    write_dashboard(log, today, cal, done["date"].max())
    write_performance(rep)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=pd.Timestamp, default=pd.Timestamp.now().normalize())
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()
    run(args.today, not args.no_download)


if __name__ == "__main__":
    main()
