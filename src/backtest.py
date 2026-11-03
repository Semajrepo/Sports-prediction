"""Walk-forward backtest: every match is predicted using only matches played before it.

Step 1 (slow, cached): weekly refit of team ratings per league -> model lambdas,
plus market-implied lambdas from pre-match average odds.
Step 2 (fast): pick the model/market blend, then score every pick category.

Usage: python src/backtest.py [--refit]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from markets import CAT1, FAMILY, KEY_INFO, TOP5, market_probs, picks_for, settle
from model import CountRatings, MarketInverter, TeamRatings, blend, count_over_prob, outcome_probs, score_matrix

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "matches.parquet"
PRED = ROOT / "data" / "backtest_lambdas.parquet"
COUNTS = ROOT / "data" / "backtest_counts.parquet"
KEYS = ["Div", "Date", "HomeTeam", "AwayTeam"]
STATS = {  # stat -> (home column, away column, use referee)
    "corners": ("HC", "AC", False),
    "cards": ("HCard", "ACard", True),
}
REPORT = ROOT / "output" / "backtest_summary.json"
TEST_FROM = pd.Timestamp("2017-07-01")   # leave two seasons of warm-up history
FIRST_EVAL_SEASON = 2019   # corners/cards calibration needs two earlier backtest seasons


def build_lambdas() -> pd.DataFrame:
    df = pd.read_parquet(DATA).dropna(subset=["FTHG", "FTAG", "Date"])
    inv = MarketInverter()
    df["lh_mkt"], df["la_mkt"] = inv.invert(df["AvgH"], df["AvgD"], df["AvgA"], df["Avg>2.5"], df["Avg<2.5"])
    df["lh_mod"], df["la_mod"] = np.nan, np.nan

    for div, d in df.groupby("Div"):
        weeks = pd.date_range(TEST_FROM, d["Date"].max() + pd.Timedelta(days=7), freq="7D")
        for start, end in zip(weeks[:-1], weeks[1:]):
            todo = d[(d["Date"] >= start) & (d["Date"] < end)]
            if todo.empty:
                continue
            r = TeamRatings().fit(d, start)
            lh, la = r.predict(todo["HomeTeam"].tolist(), todo["AwayTeam"].tolist())
            df.loc[todo.index, "lh_mod"], df.loc[todo.index, "la_mod"] = lh, la
        print(f"{div}: done")

    out = df[df["Date"] >= TEST_FROM].copy()
    PRED.parent.mkdir(exist_ok=True)
    out.to_parquet(PRED, index=False)
    return out


def add_count_inputs(df: pd.DataFrame, inv: MarketInverter | None = None) -> pd.DataFrame:
    """Market-implied expected goals (features for corners/cards) and per-team card totals."""
    inv = inv or MarketInverter()
    df = df.copy()
    df["xg_h"], df["xg_a"] = inv.invert(df["AvgH"], df["AvgD"], df["AvgA"], df["Avg>2.5"], df["Avg<2.5"])
    for c in ("xg_h", "xg_a"):  # rare games without odds: league average
        df[c] = df[c].fillna(df.groupby("Div")[c].transform("mean"))
    df["HCard"], df["ACard"] = df["HY"] + df["HR"], df["AY"] + df["AR"]
    return df


def count_columns(models: dict, d: pd.DataFrame) -> dict:
    """Predicted means, spreads and league-average baselines for each stat."""
    out = {}
    for stat, m in models.items():
        p = stat[:2]
        mh, ma = m.predict(d["HomeTeam"], d["AwayTeam"], d["xg_h"], d["xg_a"], d.get("Referee"))
        ok = m.ok
        out.update({f"{p}_mh": mh, f"{p}_ma": ma,
                    f"{p}_pt": m.phi_team if ok else np.nan, f"{p}_pT": m.phi_total if ok else np.nan,
                    f"{p}_bh": m.base_h if ok else np.nan, f"{p}_ba": m.base_a if ok else np.nan})
    return out


def counts_arg(d: pd.DataFrame) -> dict:
    """Raw (uncalibrated) `counts` argument of market_probs from count_columns output."""
    out = {}
    for stat in STATS:
        p = stat[:2]
        mh, ma = d[f"{p}_mh"].to_numpy(float), d[f"{p}_ma"].to_numpy(float)
        pt, pT = d[f"{p}_pt"].to_numpy(float), d[f"{p}_pT"].to_numpy(float)
        out[stat] = {"mh": mh, "ma": ma, "mt": mh + ma, "phi_h": pt, "phi_a": pt, "phi_t": pT}
    return out


def _count_parts(d: pd.DataFrame, stat: str) -> dict:
    """side -> (model mean, league-average mean, actual count)."""
    p = stat[:2]
    act_h = d["HC"] if stat == "corners" else d["HY"] + d["HR"]
    act_a = d["AC"] if stat == "corners" else d["AY"] + d["AR"]
    mh, ma, bh, ba = (d[f"{p}_{x}"] for x in ("mh", "ma", "bh", "ba"))
    return {"H": (mh, bh, act_h), "A": (ma, ba, act_a), "T": (mh + ma, bh + ba, act_h + act_a)}


def fit_count_calibration(d: pd.DataFrame) -> dict:
    """Out-of-sample correction for corners/cards: how far to trust the model's deviation from
    the league average (shrink, 0-1) and the real spread (phi = variance / mean)."""
    cal = {}
    for stat in STATS:
        for side, (mu, base, y) in _count_parts(d, stat).items():
            ok = mu.notna() & base.notna() & y.notna()
            mu, base, y = (x[ok].to_numpy(float) for x in (mu, base, y))
            dev = mu - base
            shrink = float(np.clip(np.sum(dev * (y - base)) / np.sum(dev ** 2), 0, 1))
            m2 = base + shrink * dev
            cal[f"{stat}_{side}"] = {"shrink": round(shrink, 4),
                                     "phi": round(float(np.mean((y - m2) ** 2) / np.mean(m2)), 4)}
    return cal


def calibrated_counts(d: pd.DataFrame, cal: dict) -> dict:
    """`counts` argument of market_probs with the calibration applied."""
    out = {}
    for stat in STATS:
        p = stat[:2]
        mh, ma, bh, ba = (d[f"{p}_{x}"].to_numpy(float) for x in ("mh", "ma", "bh", "ba"))
        c = {side: cal[f"{stat}_{side}"] for side in "HAT"}
        out[stat] = {"mh": bh + c["H"]["shrink"] * (mh - bh), "ma": ba + c["A"]["shrink"] * (ma - ba),
                     "mt": bh + ba + c["T"]["shrink"] * (mh + ma - bh - ba),
                     "phi_h": c["H"]["phi"], "phi_a": c["A"]["phi"], "phi_t": c["T"]["phi"]}
    return out


def walk_forward_counts(bt: pd.DataFrame, first_season: int) -> tuple[dict, dict]:
    """Calibrate each season on all earlier seasons only. Seasons before `first_season`
    get no corners/cards probabilities. Returns (counts for market_probs, latest calibration)."""
    n = len(bt)
    out = {stat: {k: np.full(n, np.nan) for k in ("mh", "ma", "mt", "phi_h", "phi_a", "phi_t")} for stat in STATS}
    for season in sorted(bt["Season"].unique()):
        if season < first_season:
            continue
        idx = np.flatnonzero(bt["Season"].to_numpy() == season)
        part = calibrated_counts(bt.iloc[idx], fit_count_calibration(bt[bt["Season"] < season]))
        for stat in STATS:
            for k, v in part[stat].items():
                out[stat][k][idx] = v
    return out, fit_count_calibration(bt)


def build_counts() -> pd.DataFrame:
    df = add_count_inputs(pd.read_parquet(DATA).dropna(subset=["Date"]))
    cols = [f"{s[:2]}_{x}" for s in STATS for x in ("mh", "ma", "pt", "pT", "bh", "ba")]
    for c in cols:
        df[c] = np.nan
    for div, d in df.groupby("Div"):
        weeks = pd.date_range(TEST_FROM, d["Date"].max() + pd.Timedelta(days=7), freq="7D")
        for start, end in zip(weeks[:-1], weeks[1:]):
            todo = d[(d["Date"] >= start) & (d["Date"] < end)]
            if todo.empty:
                continue
            models = {s: CountRatings(use_referee=ref).fit(d, start, hc, ac) for s, (hc, ac, ref) in STATS.items()}
            for c, v in count_columns(models, todo).items():
                df.loc[todo.index, c] = v
        print(f"{div}: counts done")
    out = df[df["Date"] >= TEST_FROM][KEYS + cols + ["HC", "AC", "HY", "AY", "HR", "AR"]]
    out.to_parquet(COUNTS, index=False)
    return out


def count_skill(bt: pd.DataFrame, won: pd.DataFrame, cal_counts: dict) -> list:
    """Log-loss of the corners/cards model (raw and calibrated) vs a league-average guess."""
    raw = counts_arg(bt)
    res = []
    for stat, line in (("corners", 9.5), ("corners", 10.5), ("cards", 3.5), ("cards", 4.5)):
        p = stat[:2]
        key = f"{p.upper()}T{line}O"
        c = cal_counts[stat]
        ok = (won[key].notna() & bt[f"{p}_mh"].notna()).to_numpy() & ~np.isnan(c["mt"])
        y = won[key].to_numpy()[ok]
        pr = count_over_prob(raw[stat]["mt"][ok], raw[stat]["phi_t"][ok], line)
        pc = count_over_prob(c["mt"][ok], c["phi_t"][ok], line)
        pb = count_over_prob((bt[f"{p}_bh"] + bt[f"{p}_ba"]).to_numpy()[ok], c["phi_t"][ok], line)
        ll = lambda q: float(-np.mean(y * np.log(np.clip(q, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - q, 1e-9, 1))))
        res.append({"market": f"{stat} over {line}", "n": int(ok.sum()), "logloss_raw_model": round(ll(pr), 4),
                    "logloss_calibrated": round(ll(pc), 4), "logloss_league_avg": round(ll(pb), 4),
                    "actual_rate": round(float(y.mean()), 4)})
    return res


def logloss_1x2(lh, la, ftr):
    p = outcome_probs(score_matrix(lh, la))
    pr = np.select([ftr == "H", ftr == "D"], [p["H"], p["D"]], p["A"])
    return -np.log(np.clip(pr, 1e-9, 1)).mean()


def evaluate(bt: pd.DataFrame, counts: pd.DataFrame) -> dict:
    bt = bt.dropna(subset=["lh_mkt", "lh_mod"])
    bt = bt.drop(columns=[c for c in counts.columns if c in bt.columns and c not in KEYS])
    bt = bt.merge(counts, on=KEYS, how="left").reset_index(drop=True)
    res = {"matches": len(bt), "from": str(bt["Date"].min().date()), "to": str(bt["Date"].max().date())}

    # --- blend weight: lowest 1X2 log-loss on matches before the last season (no peeking)
    tune = bt[bt["Season"] < bt["Season"].max() - 1]
    scores = {}
    for w in [0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        lh, la = blend(tune["lh_mod"].to_numpy(), tune["la_mod"].to_numpy(),
                       tune["lh_mkt"].to_numpy(), tune["la_mkt"].to_numpy(), w)
        scores[w] = logloss_1x2(lh, la, tune["FTR"].to_numpy())
    w_best = min(scores, key=scores.get)
    res["logloss_by_market_weight"] = {str(k): round(v, 4) for k, v in scores.items()}
    res["market_weight"] = w_best

    # --- 1st-half share of goals, estimated on the tuning period
    share = (tune["HTHG"].sum() + tune["HTAG"].sum()) / (tune["FTHG"].sum() + tune["FTAG"].sum())
    res["first_half_share"] = round(float(share), 4)

    lh, la = blend(bt["lh_mod"].to_numpy(), bt["la_mod"].to_numpy(),
                   bt["lh_mkt"].to_numpy(), bt["la_mkt"].to_numpy(), w_best)
    cal_counts, res["count_calibration"] = walk_forward_counts(bt, FIRST_EVAL_SEASON)
    probs = market_probs(lh, la, share, cal_counts)
    won = settle(bt)
    res["count_skill"] = count_skill(bt, won, cal_counts)

    # --- everything below is scored from FIRST_EVAL_SEASON, where corners/cards are out of sample
    ev = (bt["Season"] >= FIRST_EVAL_SEASON).to_numpy()
    bt, probs, won = bt[ev].reset_index(drop=True), probs[ev].reset_index(drop=True), won[ev].reset_index(drop=True)
    res.update({"matches": len(bt), "from": str(bt["Date"].min().date())})

    # --- calibration of every market: predicted vs actual hit rate
    cal = {}
    for k in probs.columns:
        ok = won[k].notna()
        cal[k] = {"pred": round(probs.loc[ok, k].mean(), 4), "actual": round(won.loc[ok, k].astype(float).mean(), 4)}
    res["calibration"] = cal

    # --- same rules without corners/cards, for comparison
    old = picks_for(probs, exclude=set(FAMILY))
    cmp = {}
    for slot in ("pick2", "pick3"):
        hits = [won.at[i, k] for i, k in old[slot].dropna().items()]
        hits = [h for h in hits if not np.isnan(h)]
        cmp[slot] = round(float(np.mean(hits)), 4)
    res["goals_only_extras_hit"] = cmp

    # --- picks: hit rate per category/option, and ROI where we have real odds
    picks = picks_for(probs, counts_ok=bt["Div"].isin(TOP5).to_numpy())
    odds = pd.DataFrame({
        "1": bt["AvgH"], "2": bt["AvgA"],
        # double chance price implied from 1X2 (books' DC margins are similar)
        "1X": 1 / (1 / bt["AvgH"] + 1 / bt["AvgD"]), "X2": 1 / (1 / bt["AvgA"] + 1 / bt["AvgD"]),
        "O2.5": bt["Avg>2.5"], "U2.5": bt["Avg<2.5"],
    })
    rows = []
    for slot in ("pick1", "pick2", "pick3"):
        for i, k in picks[slot].dropna().items():
            rows.append({"slot": slot, "key": k, "p": picks.at[i, f"{slot}_p"], "won": won.at[i, k],
                         "odds": odds.at[i, k] if k in odds.columns else np.nan,
                         "season": bt.at[i, "Season"], "league": bt.at[i, "League"]})
    pk = pd.DataFrame(rows).dropna(subset=["won"])
    pk["won"] = pk["won"].astype(float)
    pk["category"] = pk["key"].map(lambda k: KEY_INFO[k][0])
    pk["label"] = pk["key"].map(lambda k: KEY_INFO[k][1])
    pk["profit"] = np.where(pk["won"] == 1, pk["odds"] - 1, -1.0)

    def summ(g):
        has = g["odds"].notna()
        return pd.Series({
            "n": len(g), "pred": g["p"].mean(), "hit": g["won"].mean(),
            "roi": g.loc[has, "profit"].mean() if has.any() else np.nan,
            "n_odds": int(has.sum()),
        })

    res["by_option"] = pk.groupby(["category", "label"]).apply(summ, include_groups=False) \
        .round(4).reset_index().sort_values("n", ascending=False).to_dict("records")
    res["by_slot"] = pk.groupby("slot").apply(summ, include_groups=False).round(4).reset_index().to_dict("records")
    res["by_league_cat1"] = pk[pk["slot"] == "pick1"].groupby("league").apply(summ, include_groups=False) \
        .round(4).reset_index().sort_values("hit", ascending=False).to_dict("records")
    # all three picks of a match landing (a 3-leg same-game combo)
    trip = []
    for i, r in picks.dropna(subset=["pick3"]).iterrows():
        w = [won.at[i, r[s]] for s in ("pick1", "pick2", "pick3")]
        if not any(pd.isna(x) for x in w):
            trip.append((r["pick1_p"] * r["pick2_p"] * r["pick3_p"], float(all(w))))
    trip = np.array(trip)
    res["all_three_hit"] = {"n": len(trip), "naive_pred": round(trip[:, 0].mean(), 4), "actual": round(trip[:, 1].mean(), 4)}

    # bucketed reliability for the cat-1 pick
    c1 = pk[pk["slot"] == "pick1"].copy()
    c1["bucket"] = pd.cut(c1["p"], [0, .6, .65, .7, .75, .8, .85, .9, 1])
    res["cat1_reliability"] = c1.groupby("bucket", observed=True).agg(n=("won", "size"), pred=("p", "mean"), hit=("won", "mean")) \
        .round(4).reset_index().astype({"bucket": str}).to_dict("records")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    args = ap.parse_args()
    bt = build_lambdas() if args.refit or not PRED.exists() else pd.read_parquet(PRED)
    counts = build_counts() if args.refit or not COUNTS.exists() else pd.read_parquet(COUNTS)
    res = evaluate(bt, counts)
    import json
    REPORT.parent.mkdir(exist_ok=True)
    if REPORT.exists():   # keep results other scripts added (support check, best pick)
        prev = json.loads(REPORT.read_text())
        res.update({k: prev[k] for k in ("support_check", "best_pick") if k in prev})
    REPORT.write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({k: v for k, v in res.items() if k not in ("calibration", "by_option")}, indent=1, default=str))
    print(pd.DataFrame(res["by_option"]).to_string())


if __name__ == "__main__":
    main()
