"""Write the dashboard's data files from the picks record and the backtest summary.

  upcoming.csv   one row per match in the prediction window (next 3 days), three picks each
  history.csv    one row per pick already played: live picks plus the labelled test picks
  status.csv     when the data was last updated and what the window covers
  backtest_*.csv, cat1_reliability.csv, league_cat1.csv, support_check.csv   performance

Usage: python src/export_dashboard.py [--today 2026-10-27] [--days 3]   (rebuilds from the record only;
`python src/update.py` downloads, predicts and then calls this)
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from markets import CAT1, FAMILY

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "dashboard"
LOG = ROOT / "output" / "picks_log.csv"
TEST_HISTORY = ROOT / "output" / "test_history.csv"
REPORT = ROOT / "output" / "backtest_summary.json"
# The backtest showed these labels don't change the chance of winning beyond the
# probability, so they are shown as plain descriptions, not as safety grades.
SUPPORT_LABEL = {"strong": "History agrees", "fair": "History mostly agrees",
                 "mixed": "History split", "model only": "Little history"}
SOURCE = {"before kickoff": "Live", "back-check": "Back-check"}


def match_id(date: str, home: str, away: str) -> str:
    slug = lambda s: re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return f"{date}-{slug(home)}-{slug(away)}"


def family(category: str) -> str:
    """Market family shown as a colour on the dashboard: Result, Goals, Corners or Cards."""
    if category == CAT1:
        return "Result"
    return {"corners": "Corners", "cards": "Cards"}.get(FAMILY.get(category), "Goals")


def flat_picks(log: pd.DataFrame, source_col="made") -> pd.DataFrame:
    """One row per pick from per-match rows."""
    rows = []
    for _, m in log.iterrows():
        for i in (0, 1, 2, 3):
            if not isinstance(m.get(f"pick{i}"), str) or not m[f"pick{i}"]:
                continue
            won = m.get(f"pick{i}_won", "")
            rows.append({
                "pick_id": f"{m['match_id']}|{i}", "match_id": m["match_id"], "date": m["date"],
                "competition": m["league"], "home": m["home"], "away": m["away"], "result": m.get("result", ""),
                "slot": "Best" if i == 0 else f"Pick {i}", "family": family(m[f"pick{i}_market"]), "market": m[f"pick{i}_market"],
                "pick": m[f"pick{i}"], "prob": m[f"pick{i}_prob"], "fair_odds": m[f"pick{i}_odds"],
                "outcome": won if won in ("won", "lost") else "pending",
                "source": SOURCE.get(m.get(source_col, ""), m.get(source_col, "")),
            })
    return pd.DataFrame(rows)


def write_performance(bt: dict):
    opt = pd.DataFrame(bt["by_option"]).rename(columns={"label": "option", "pred": "predicted", "hit": "hit_rate"})
    opt["roi"] = opt["roi"].where(opt["n_odds"] >= 200)  # fewer priced bets than this is noise
    opt["family"] = opt["category"].map(family)
    opt[["family", "category", "option", "n", "predicted", "hit_rate", "roi", "n_odds"]].to_csv(OUT / "backtest_options.csv", index=False)

    slot_names = {"pick1": "Pick 1 · 1X2 / Double Chance", "pick2": "Pick 2 · safest other market", "pick3": "Pick 3 · next market"}
    sl = pd.DataFrame(bt["by_slot"]).rename(columns={"pred": "predicted", "hit": "hit_rate"})
    sl["slot_name"] = sl["slot"].map(slot_names)
    sl["roi"] = sl["roi"].where(sl["n_odds"] >= 200)
    if "best_pick" in bt:
        b = bt["best_pick"]
        sl = pd.concat([pd.DataFrame([{"slot": "best", "slot_name": "Best pick", "n": b["n"], "predicted": b["pred"], "hit_rate": b["hit"]}]), sl])
    trip = bt["all_three_hit"]
    sl = pd.concat([sl, pd.DataFrame([{"slot": "all3", "slot_name": "All three in one match", "n": trip["n"],
                                       "predicted": trip["naive_pred"], "hit_rate": trip["actual"]}])])
    sl[["slot", "slot_name", "n", "predicted", "hit_rate", "roi"]].to_csv(OUT / "backtest_slots.csv", index=False)

    rel = pd.DataFrame(bt["cat1_reliability"]).rename(columns={"pred": "predicted", "hit": "hit_rate"})
    rel["bucket"] = rel["bucket"].map(  # "(0.6, 0.65]" -> "60–65%"
        lambda b: "–".join(f"{float(x) * 100:.0f}" for x in b.strip("(]").split(", ")) + "%")
    rel.to_csv(OUT / "cat1_reliability.csv", index=False)

    lg = pd.DataFrame(bt["by_league_cat1"]).rename(columns={"pred": "predicted", "hit": "hit_rate"})
    lg[["league", "n", "predicted", "hit_rate", "roi"]].to_csv(OUT / "league_cat1.csv", index=False)

    if "support_check" in bt:  # hit rate by probability band (rows) and support label (columns)
        sc = pd.DataFrame(bt["support_check"]["by_band"]).T
        sc = sc.rename(columns={"strong": "agrees", "fair": "mostly_agrees", "mixed": "split"})
        sc.index.name = "band"
        sc[["agrees", "mostly_agrees", "split"]].reset_index().to_csv(OUT / "support_check.csv", index=False)


def write_dashboard(log: pd.DataFrame, today: pd.Timestamp, days: int, data_through: str | None = None):
    OUT.mkdir(parents=True, exist_ok=True)
    t0, t1 = today.strftime("%Y-%m-%d"), (today + pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d")

    up = log[(log["date"] >= t0) & (log["date"] <= t1)].copy()
    for i in (0, 1, 2, 3):
        up[f"pick{i}_family"] = up[f"pick{i}_market"].map(lambda c: family(c) if isinstance(c, str) and c else "")
    # the dashboard shows chances only, no prices: odds stay in the record, not in its files
    up = up.drop(columns=[c for c in up.columns if c.endswith("_odds") or "_book_" in c])
    up.to_csv(OUT / "upcoming.csv", index=False)

    live = flat_picks(log[log["date"] < t0])
    test = pd.read_csv(TEST_HISTORY, dtype=str, keep_default_na=False) if TEST_HISTORY.exists() else pd.DataFrame()
    hist = pd.concat([live, test], ignore_index=True)
    hist = hist[~hist.duplicated("pick_id", keep="first")]   # a live pick wins over a test pick of the same game
    hist = hist.sort_values(["date", "competition", "home", "slot"], ascending=[False, True, True, True])
    hist.drop(columns=["fair_odds"], errors="ignore").to_csv(OUT / "history.csv", index=False)

    pd.DataFrame([{
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "data_through": data_through or "",
        "window_from": t0, "window_to": t1, "days": days, "upcoming_matches": len(up),
        "live_picks": int((hist["source"] != "Test").sum()), "test_picks": int((hist["source"] == "Test").sum()),
    }]).to_csv(OUT / "status.csv", index=False)

    write_performance(json.loads(REPORT.read_text())) if REPORT.exists() else None
    for f in sorted(OUT.glob("*.csv")):
        print(f"  {f.name:24s} {f.stat().st_size:>9,d} bytes")
    return up, hist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", type=pd.Timestamp, default=pd.Timestamp.now().normalize())
    ap.add_argument("--days", type=int, default=3)
    args = ap.parse_args()
    log = pd.read_csv(LOG, dtype=str, keep_default_na=False)
    write_dashboard(log, args.today, args.days)


if __name__ == "__main__":
    main()
