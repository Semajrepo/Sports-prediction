"""Test picks for the History page until real history builds up.

Takes the walk-forward backtest (every match predicted from earlier matches only) for a
date range and writes its picks, with results, to output/test_history.csv. They are
labelled "Test" on the dashboard so they are never mistaken for live predictions.

Usage: python src/build_test_history.py [--from 2025-08-01] [--to 2026-10-22]
"""
import argparse
import json

import numpy as np
import pandas as pd

from backtest import COUNTS, FIRST_EVAL_SEASON, KEYS, PRED, REPORT, walk_forward_counts
from export_dashboard import TEST_HISTORY, family, match_id
from markets import KEY_INFO, TOP5, market_probs, picks_for, settle
from model import blend


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="2025-08-01")
    ap.add_argument("--to", dest="end", default="2026-10-22")
    args = ap.parse_args()
    cfg = json.loads(REPORT.read_text())

    bt = pd.read_parquet(PRED).dropna(subset=["lh_mkt", "lh_mod"])
    counts = pd.read_parquet(COUNTS)
    bt = bt.drop(columns=[c for c in counts.columns if c in bt.columns and c not in KEYS])
    bt = bt.merge(counts, on=KEYS, how="left").reset_index(drop=True)
    cc, _ = walk_forward_counts(bt, FIRST_EVAL_SEASON)
    keep = ((bt["Date"] >= args.start) & (bt["Date"] <= args.end)).to_numpy()
    bt = bt[keep].reset_index(drop=True)
    cc = {stat: {k: v[keep] for k, v in c.items()} for stat, c in cc.items()}

    lh, la = blend(bt["lh_mod"].to_numpy(), bt["la_mod"].to_numpy(), bt["lh_mkt"].to_numpy(), bt["la_mkt"].to_numpy(), cfg["market_weight"])
    probs = market_probs(lh, la, cfg["first_half_share"], cc)
    picks = picks_for(probs, counts_ok=bt["Div"].isin(TOP5).to_numpy())
    won = settle(bt)

    rows = []
    for i, m in bt.iterrows():
        date = m["Date"].strftime("%Y-%m-%d")
        mid = match_id(date, m["HomeTeam"], m["AwayTeam"])
        for n, slot in enumerate(("pick0", "pick1", "pick2", "pick3")):
            k = picks.at[i, slot]
            if not isinstance(k, str):
                continue
            cat, label = KEY_INFO[k]
            p = float(picks.at[i, f"{slot}_p"])
            w = won.at[i, k]
            rows.append({
                "pick_id": f"{mid}|{n}", "match_id": mid, "date": date, "competition": m["League"],
                "home": m["HomeTeam"], "away": m["AwayTeam"], "result": f"{int(m['FTHG'])}-{int(m['FTAG'])}",
                "slot": "Best" if n == 0 else f"Pick {n}", "family": family(cat), "market": cat, "pick": label,
                "prob": round(p, 3), "fair_odds": round(1 / p, 2),
                "outcome": "pending" if np.isnan(w) else ("won" if w == 1 else "lost"), "source": "Test",
            })
    out = pd.DataFrame(rows)
    out.to_csv(TEST_HISTORY, index=False)
    print(f"{len(out):,} test picks for {bt.shape[0]:,} matches, {args.start} to {args.end}; "
          f"{TEST_HISTORY.stat().st_size:,} bytes")
    print(out.groupby("family").agg(n=("outcome", "size"), won=("outcome", lambda s: (s == "won").mean()),
                                    pred=("prob", "mean")).round(3).to_string())


if __name__ == "__main__":
    main()
