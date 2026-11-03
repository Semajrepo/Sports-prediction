"""Walk-forward volleyball backtest and calibration.

Every week from Sep 2023 the ratings are refitted on games before that week only, then
that week's games are predicted. Shrink and spread are fitted on the 2023/24 season and
checked on 2024/25 (games the calibration never saw). Writes:
  data/volleyball/backtest.parquet           one row per game: rally chance q, result
  output/volley_summary.json                 calibration, best-pick record, per-market record

Usage: python src/volley_backtest.py [--refit]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from volley_download import DIR
from volley_model import KEY_INFO, SCORES, Ratings, finished, market_probs, settle

ROOT = Path(__file__).resolve().parent.parent
PRED = DIR / "backtest.parquet"
REPORT = ROOT / "output" / "volley_summary.json"
START = pd.Timestamp("2023-09-01")
CALIB_END = pd.Timestamp("2024-07-01")   # calibrate before this, test after
BEST_MAX = 0.79                          # same rule as football: safest pick up to 79%
BEST_MIN = 0.55                          # one-sided games with nothing between: no best pick


def walk_forward(g: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dates = pd.to_datetime(g["date"])
    weeks = pd.date_range(START, dates.max() + pd.Timedelta(days=7), freq="W-MON")
    for wk in weeks:
        nxt = g[(dates >= wk) & (dates < wk + pd.Timedelta(days=7))]
        if nxt.empty:
            continue
        r = Ratings().fit(g, wk)
        for _, m in nxt.iterrows():
            seen = min(r.games_seen.get(m["home_id"], 0), r.games_seen.get(m["away_id"], 0))
            rows.append({"game_id": m["game_id"], "q": r.rally_prob(m["home_id"], m["away_id"], m["league"]), "seen": seen})
        print(f"  week of {wk.date()}: {len(nxt)} games", end="\r")
    print()
    return g.merge(pd.DataFrame(rows), on="game_id")


def set_score_loglik(bt: pd.DataFrame, shrink, spread) -> float:
    """Log-likelihood of the final set scores (how well the model spreads chance over 3-0 ... 0-3)."""
    from volley_model import expit, logit, set_scores, set_win, GH_X, GH_W
    q = bt["q"].to_numpy()
    tot = np.zeros(len(q))
    key = (bt["hs"].astype(int).astype(str) + "-" + bt["as"].astype(int).astype(str)).to_numpy()
    for x, w in zip(GH_X, GH_W):
        qq = expit(logit(q) + spread * x)
        p = expit(shrink * logit(set_win(qq, 25)))
        p5 = expit(shrink * logit(set_win(qq, 15)))
        sc = set_scores(p, p5)
        tot += w * np.select([key == k for k in sc], list(sc.values()))
    return float(np.log(np.clip(tot, 1e-12, None)).sum())


def fit_calibration(bt: pd.DataFrame) -> dict:
    res = minimize(lambda v: -set_score_loglik(bt, v[0], abs(v[1])), x0=[0.8, 0.1], method="Nelder-Mead")
    return {"shrink": round(float(res.x[0]), 4), "spread": round(abs(float(res.x[1])), 4)}


def best_pick(p: pd.Series, p_max=BEST_MAX):
    ok = p[(p <= p_max) & (p >= BEST_MIN)]
    return (ok.idxmax(), float(ok.max())) if len(ok) else (None, np.nan)


def evaluate(bt: pd.DataFrame, cal: dict) -> dict:
    probs = market_probs(bt["q"].to_numpy(), cal["shrink"], cal["spread"])
    won = settle(bt.reset_index(drop=True))
    test = (pd.to_datetime(bt["date"]) >= CALIB_END).to_numpy()
    out = {"calibration": cal, "games": int(len(bt)), "test_games": int(test.sum()),
           "from": str(bt["date"].min()), "to": str(bt["date"].max())}

    # per market: average stated chance vs how often it won (test games only)
    rows = []
    for k in KEY_INFO:
        rows.append({"key": k, "category": KEY_INFO[k][0], "label": KEY_INFO[k][1],
                     "pred": round(float(probs.loc[test, k].mean()), 4), "hit": round(float(won.loc[test, k].mean()), 4)})
    out["by_market"] = rows

    picks = [best_pick(probs.iloc[i]) for i in range(len(probs))]
    bt = bt.reset_index(drop=True).assign(pick=[k for k, _ in picks], p=[v for _, v in picks])
    bt["won"] = [won.at[i, k] if isinstance(k, str) else np.nan for i, k in enumerate(bt["pick"])]
    t = bt[test].dropna(subset=["won"])
    out["best_pick"] = {"n": int(len(t)), "pred": round(float(t["p"].mean()), 4), "hit": round(float(t["won"].mean()), 4)}
    out["best_by_market"] = (t.groupby("pick").agg(n=("won", "size"), pred=("p", "mean"), hit=("won", "mean"))
                              .round(4).reset_index().sort_values("n", ascending=False).to_dict("records"))
    out["best_by_league"] = (t.groupby("league").agg(n=("won", "size"), pred=("p", "mean"), hit=("won", "mean"))
                              .round(4).reset_index().sort_values("hit", ascending=False).to_dict("records"))
    t = t.assign(band=pd.cut(t["p"], [0.5, 0.6, 0.65, 0.7, 0.75, 0.8]))
    out["best_reliability"] = [{"band": str(b), "n": int(len(x)), "pred": round(float(x["p"].mean()), 4),
                                "hit": round(float(x["won"].mean()), 4)} for b, x in t.groupby("band", observed=True)]
    bt.to_parquet(DIR / "backtest_picks.parquet")
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true", help="redo the walk-forward ratings (a few minutes)")
    args = ap.parse_args()
    g = finished(pd.read_csv(DIR / "games.csv"))
    if args.refit or not PRED.exists():
        bt = walk_forward(g)
        bt.to_parquet(PRED)
    bt = pd.read_parquet(PRED)
    cal = fit_calibration(bt[pd.to_datetime(bt["date"]) < CALIB_END])
    print("calibration:", cal)
    rep = evaluate(bt, cal)
    REPORT.write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps({k: rep[k] for k in ("games", "test_games", "best_pick", "best_reliability")}, indent=1))
    print(pd.DataFrame(rep["by_market"]).to_string(index=False))
    print(pd.DataFrame(rep["best_by_market"]).to_string(index=False))
    print(pd.DataFrame(rep["best_by_league"]).to_string(index=False))


if __name__ == "__main__":
    main()
