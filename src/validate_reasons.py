"""Does the 'support' label (from form and head-to-head) say anything the probability doesn't?

Replays the backtest picks from --from-season onward, labels each pick with the support it
would have had before kickoff, and compares hit rates by label at similar probabilities.
Adds the result to output/backtest_summary.json as "support_check".

Usage: python src/validate_reasons.py [--from-season 2024]
"""
import argparse
import json

import numpy as np
import pandas as pd

from backtest import COUNTS, DATA, FIRST_EVAL_SEASON, KEYS, PRED, REPORT, walk_forward_counts
from markets import KEY_INFO, market_probs, picks_for, settle
from model import blend
from reasons import History, explain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-season", type=int, default=2024)
    args = ap.parse_args()
    cfg = json.loads(REPORT.read_text())

    bt = pd.read_parquet(PRED).dropna(subset=["lh_mkt", "lh_mod"])
    counts = pd.read_parquet(COUNTS)
    bt = bt.drop(columns=[c for c in counts.columns if c in bt.columns and c not in KEYS])
    bt = bt.merge(counts, on=KEYS, how="left")
    bt = bt.reset_index(drop=True)
    cc, _ = walk_forward_counts(bt, FIRST_EVAL_SEASON)
    keep = (bt["Season"] >= args.from_season).to_numpy()
    bt = bt[keep].reset_index(drop=True)
    cc = {stat: {k: v[keep] for k, v in c.items()} for stat, c in cc.items()}
    lh, la = blend(bt["lh_mod"].to_numpy(), bt["la_mod"].to_numpy(), bt["lh_mkt"].to_numpy(), bt["la_mkt"].to_numpy(), cfg["market_weight"])
    probs = market_probs(lh, la, cfg["first_half_share"], cc)
    bt["co_mh"], bt["co_ma"] = cc["corners"]["mh"], cc["corners"]["ma"]
    bt["ca_mh"], bt["ca_ma"] = cc["cards"]["mh"], cc["cards"]["ma"]
    picks = picks_for(probs)
    won = settle(bt)

    hist = pd.read_parquet(DATA)
    past = History(hist, bt["Date"].min())
    rows = []
    for i, m in bt.iterrows():
        past.set_asof(m["Date"])
        extra = {"xg_h": lh[i], "xg_a": la[i], "co_h": m["co_mh"], "co_a": m["co_ma"],
                 "ca_h": m["ca_mh"], "ca_a": m["ca_ma"], "referee": m.get("Referee")}
        for slot in ("pick1", "pick2", "pick3"):
            k = picks.at[i, slot]
            if not isinstance(k, str) or np.isnan(won.at[i, k]):
                continue
            _, support = explain(past, m["HomeTeam"], m["AwayTeam"], k, probs.loc[i], extra)
            rows.append({"slot": slot, "category": KEY_INFO[k][0], "p": picks.at[i, f"{slot}_p"],
                         "won": won.at[i, k], "support": support})
        if i % 2000 == 0:
            print(f"{i}/{len(bt)}")

    df = pd.DataFrame(rows)
    df["band"] = pd.cut(df["p"], [0, .7, .8, .9], labels=["55–70%", "70–80%", "80–85%"])
    by_support = df.groupby("support").agg(n=("won", "size"), predicted=("p", "mean"), hit_rate=("won", "mean")).round(4)
    by_band = df.pivot_table(index="band", columns="support", values="won", aggfunc="mean", observed=True).round(4)
    print(by_support.to_string(), "\n\nHit rate by probability band and support:\n", by_band.to_string())

    cfg["support_check"] = {
        "from_season": args.from_season, "picks": len(df),
        "by_support": by_support.reset_index().to_dict("records"),
        "by_band": {str(b): {s: (None if pd.isna(v) else v) for s, v in r.items()} for b, r in by_band.iterrows()},
    }
    REPORT.write_text(json.dumps(cfg, indent=2, default=str))


if __name__ == "__main__":
    main()
