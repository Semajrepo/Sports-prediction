"""Daily update: refresh the dataset, retrain on it, pick the next few days, fill in results.

1. Download the latest results and fixture list from football-data.co.uk.
2. Fit every model on all matches played so far and make picks for fixtures from today
   through the next `--days` days.
3. Add those picks to output/picks_log.csv. A match's picks are frozen from its match day
   on, so the record always holds the last prediction made before kickoff.
4. Fill in results and won/lost for past picks from the updated dataset.
5. Write the dashboard files (see export_dashboard.py).

Usage: python src/update.py [--days 3] [--today 2026-10-27] [--no-download]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import REPORT, add_count_inputs
from download import LEAGUES
from europe import EURO, LEAGUE_ODDS, api_key, europe_fixtures, update_results
from results90 import api_key as results90_key, ninety_minute_results
from export_dashboard import LOG, SUPPORT_LABEL, match_id, write_dashboard
from markets import KEY_INFO, settle
from model import MarketInverter
from predict import FIXTURES, RESULT_COLS, check_names, load_fixtures, predict_fixtures

ROOT = Path(__file__).resolve().parent.parent
LABEL_TO_KEY = {label: k for k, (_, label) in KEY_INFO.items()}
DIV_OF = {name: div for div, name in LEAGUES.items()}
PICK_FIELDS = ("key", "market", "", "prob", "odds", "won", "why", "support")


def to_log_rows(rows: list[dict], today: str) -> pd.DataFrame:
    out = []
    for m in rows:
        r = {"match_id": match_id(m["date"], m["home"], m["away"]),
             "made": "before kickoff" if today <= m["date"] else "back-check", "made_on": today,
             "date": m["date"], "time": m["time"], "div": m["div"], "league": m["league"],
             "home": m["home"], "away": m["away"], "referee": m.get("referee", ""), "result": "",
             "xg_home": m["xg_home"], "xg_away": m["xg_away"], "p_home": m["p_home"], "p_draw": m["p_draw"],
             "p_away": m["p_away"], "safety": m["safety"]}
        for p in m["picks"]:
            i = p.get("slot", 0)
            r.update({f"pick{i}_key": p["key"], f"pick{i}_market": p["category"], f"pick{i}": p["pick"],
                      f"pick{i}_prob": p["prob"], f"pick{i}_odds": p["fair_odds"], f"pick{i}_won": "",
                      f"pick{i}_book_avg": "" if p.get("book_avg") is None else p["book_avg"],
                      f"pick{i}_book_best": "" if p.get("book_best") is None else p["book_best"],
                      f"pick{i}_book_note": p.get("book_note", ""),
                      f"pick{i}_why": p["why"], f"pick{i}_support": SUPPORT_LABEL.get(p["support"], p["support"])})
        out.append(r)
    return pd.DataFrame(out).astype(str)


def load_log() -> pd.DataFrame:
    if not LOG.exists():
        return pd.DataFrame()
    log = pd.read_csv(LOG, dtype=str, keep_default_na=False)
    # records written before the daily update existed
    log = log.drop(columns=[c for c in ("round",) if c in log])
    if "made_on" not in log:
        log["made_on"] = ""
    if "div" not in log:
        log["div"] = log["league"].map(DIV_OF).fillna("")
    for i in (1, 2, 3):
        if f"pick{i}_key" not in log:
            log[f"pick{i}_key"] = log[f"pick{i}"].map(LABEL_TO_KEY).fillna("")
    for c in ("key", "market", "", "prob", "won", "why", "support"):   # records from before the best pick existed
        col = f"pick0_{c}" if c else "pick0"
        if col not in log:
            log[col] = ""
    return log


def merge(log: pd.DataFrame, new: pd.DataFrame, today: str) -> pd.DataFrame:
    if log.empty:
        return new
    if new.empty:
        return log
    frozen = set(log.loc[log["date"] <= today, "match_id"])     # match day reached: keep what was made
    new = new[~new["match_id"].isin(frozen)]
    out = pd.concat([log[~log["match_id"].isin(new["match_id"])], new], ignore_index=True)
    return out.fillna("").sort_values(["date", "time", "league", "home"]).reset_index(drop=True)


def fill_results(log: pd.DataFrame, hist: pd.DataFrame, extra: pd.DataFrame | None = None) -> int:
    """Write scores and won/lost for every past pick the dataset (plus `extra` results,
    e.g. European games) now has a result for."""
    played = hist.dropna(subset=["FTHG", "FTAG"]).copy()
    played["date"] = played["Date"].dt.strftime("%Y-%m-%d")
    if extra is not None and len(extra):
        played = pd.concat([played, extra.assign(date=extra["Date"].astype(str))], ignore_index=True)
    played = played.drop_duplicates(["Div", "date", "HomeTeam", "AwayTeam"]).set_index(["Div", "date", "HomeTeam", "AwayTeam"])
    n = 0
    # games without a score, or with a pick still open (corners/cards wait for the full league data)
    open_pick = (log["result"] == "") | pd.concat([(log[f"pick{i}_key"] != "") & (log[f"pick{i}_won"] == "")
                                                    for i in (0, 1, 2, 3) if f"pick{i}_key" in log], axis=1).any(axis=1)
    for idx, m in log[open_pick & (log["date"] < pd.Timestamp.now().strftime("%Y-%m-%d"))].iterrows():
        k = (m["div"], m["date"], m["home"], m["away"])
        if k not in played.index:
            continue
        row = played.loc[[k], RESULT_COLS].reset_index(drop=True)
        new = m["result"] == ""
        log.at[idx, "result"] = f"{int(row.at[0, 'FTHG'])}-{int(row.at[0, 'FTAG'])}"
        for i in (0, 1, 2, 3):
            key = m.get(f"pick{i}_key", "")
            if key and m.get(f"pick{i}_won", "") == "":
                w = settle(row, only={key})[key].iloc[0]
                log.at[idx, f"pick{i}_won"] = "" if np.isnan(w) else ("won" if w == 1 else "lost")
        n += new
    return n


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--today", type=pd.Timestamp)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--no-europe", action="store_true", help="skip The Odds API (saves credits)")
    ap.add_argument("--no-results90", action="store_true", help="skip API-Football's 90-minute results")
    ap.add_argument("--no-volleyball", action="store_true", help="skip the volleyball picks")
    args = ap.parse_args()
    today = args.today or pd.Timestamp.now().normalize()
    t = today.strftime("%Y-%m-%d")

    if not args.no_download:
        subprocess.run([sys.executable, str(ROOT / "src" / "download.py")], check=True)

    cfg = json.loads(REPORT.read_text())
    inv = MarketInverter()
    hist = add_count_inputs(pd.read_parquet(ROOT / "data" / "matches.parquet").dropna(subset=["Date"]), inv)
    fx = load_fixtures(FIXTURES, not args.no_download)
    fx = fx[(fx["Date"] >= today) & (fx["Date"] < today + pd.Timedelta(days=args.days))]
    print(f"\nWindow {t} + {args.days} days: {len(fx)} league fixtures")
    key = None if args.no_europe else api_key()
    if key:
        try:
            efx = europe_fixtures(today, args.days, hist, key)
            fx = pd.concat([fx, efx], ignore_index=True) if len(efx) else fx
        except Exception as e:   # a European outage must not stop the league picks
            print(f"  ! European competitions skipped: {e}")
    elif not args.no_europe:
        print("  European competitions skipped: no API key in config/odds_api_key.txt")
    if key:   # leagues football-data.co.uk hasn't listed yet: take them from The Odds API
        missing = {d: (LEAGUE_ODDS[d], LEAGUES[d]) for d in LEAGUE_ODDS if d not in set(fx["Div"])}
        if missing:
            print(f"  Not yet on football-data.co.uk: {', '.join(missing)}; trying The Odds API")
            try:
                lfx = europe_fixtures(today, args.days, hist, key, comps=missing)
                fx = pd.concat([fx, lfx], ignore_index=True) if len(lfx) else fx
            except Exception as e:
                print(f"  ! League fallback skipped: {e}")

    new = pd.DataFrame()
    if len(fx):
        check_names(fx[~fx["Div"].isin(EURO)], hist)
        FIXTURES.with_name(f"fixtures_{t}.csv").write_bytes(FIXTURES.read_bytes())
        new = to_log_rows(predict_fixtures(fx, hist, today, cfg, inv), t)
    log = merge(load_log(), new, t)
    extra = []   # results from outside the league data, 90-minute scores first
    af_key = None if args.no_results90 else results90_key()
    if af_key:
        try:
            extra.append(ninety_minute_results(log, today, hist, af_key))
        except Exception as e:
            print(f"  ! 90-minute results skipped: {e}")
    if key:
        try:
            extra.append(update_results(log, today, hist, key))
        except Exception as e:
            print(f"  ! European results skipped: {e}")
    extra = [x for x in extra if x is not None and len(x)]
    settled = fill_results(log, hist, pd.concat(extra, ignore_index=True) if extra else None)
    LOG.parent.mkdir(exist_ok=True)
    log.to_csv(LOG, index=False)

    data_through = hist.dropna(subset=["FTHG"])["Date"].max().strftime("%Y-%m-%d")
    print(f"Record: {len(log)} matches; {settled} newly settled; results in the data up to {data_through}")
    write_dashboard(log, today, args.days, data_through)

    if not args.no_volleyball:
        try:   # a volleyball problem must not stop the football picks
            from volley_update import run as volley_run
            print("\nVolleyball")
            volley_run(today, download=not args.no_download)
        except Exception as e:
            print(f"  ! Volleyball skipped: {e}")


if __name__ == "__main__":
    main()
