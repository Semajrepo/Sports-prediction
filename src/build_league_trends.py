"""Long-run results per league, season and market type, for the dashboard's competition view.

Runs the pick rules over the whole walk-forward backtest (every match predicted from earlier
matches only, Jul 2019 onward) and counts, for each league, season and market type, how many
picks were made, how many won and the average stated probability. Writes
output/dashboard/league_seasons.csv (a few thousand rows, small enough to load with the page).

Usage: python src/build_league_trends.py
"""
import json

import numpy as np
import pandas as pd

from backtest import COUNTS, FIRST_EVAL_SEASON, KEYS, PRED, REPORT, walk_forward_counts
from export_dashboard import OUT, family
from markets import KEY_INFO, TOP5, market_probs, picks_for, settle
from model import blend


def main():
    cfg = json.loads(REPORT.read_text())
    bt = pd.read_parquet(PRED).dropna(subset=["lh_mkt", "lh_mod"])
    counts = pd.read_parquet(COUNTS)
    bt = bt.drop(columns=[c for c in counts.columns if c in bt.columns and c not in KEYS])
    bt = bt.merge(counts, on=KEYS, how="left").reset_index(drop=True)
    cc, _ = walk_forward_counts(bt, FIRST_EVAL_SEASON)
    keep = (bt["Season"] >= FIRST_EVAL_SEASON).to_numpy()
    bt = bt[keep].reset_index(drop=True)
    cc = {stat: {k: v[keep] for k, v in c.items()} for stat, c in cc.items()}

    lh, la = blend(bt["lh_mod"].to_numpy(), bt["la_mod"].to_numpy(), bt["lh_mkt"].to_numpy(), bt["la_mkt"].to_numpy(), cfg["market_weight"])
    probs = market_probs(lh, la, cfg["first_half_share"], cc)
    picks = picks_for(probs, counts_ok=bt["Div"].isin(TOP5).to_numpy())
    won = settle(bt)

    rows = []
    for slot in ("pick0", "pick1", "pick2", "pick3"):
        k = picks[slot]
        ok = k.notna()
        idx = np.flatnonzero(ok.to_numpy())
        keys = k[ok].to_numpy()
        w = np.array([won.at[i, key] for i, key in zip(idx, keys)])
        rows.append(pd.DataFrame({
            "league": bt.loc[idx, "League"].to_numpy(), "season": bt.loc[idx, "Season"].to_numpy(),
            "slot": "Best" if slot == "pick0" else "Other",
            "family": [family(KEY_INFO[key][0]) for key in keys], "p": picks.loc[idx, f"{slot}_p"].to_numpy(), "won": w}))
    pk = pd.concat(rows, ignore_index=True).dropna(subset=["won"])
    out = (pk.groupby(["slot", "league", "season", "family"])
             .agg(n=("won", "size"), won=("won", "sum"), predicted=("p", "mean")).reset_index())
    out["season"] = out["season"].map(lambda y: f"{y}/{str(y + 1)[2:]}")
    out["won"] = out["won"].astype(int)
    out["predicted"] = out["predicted"].round(4)
    out.to_csv(OUT / "league_seasons.csv", index=False)

    best = pk[pk["slot"] == "Best"]
    cfg["best_pick"] = {"n": int(len(best)), "pred": round(float(best["p"].mean()), 4), "hit": round(float(best["won"].mean()), 4)}
    REPORT.write_text(json.dumps(cfg, indent=2, default=str))
    print("best pick:", cfg["best_pick"])
    tot = out[out["slot"] == "Best"].groupby("league").agg(n=("n", "sum"), won=("won", "sum"))
    tot["rate"] = (tot["won"] / tot["n"]).round(3)
    print(f"{len(out)} rows -> {OUT / 'league_seasons.csv'}")
    print(tot.sort_values("rate", ascending=False).to_string())


if __name__ == "__main__":
    main()
