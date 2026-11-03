"""One-off patch: walk-forward calibration for corners/cards (applied once, kept for the record)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sub(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"{path}: {old[:70]!r}"
    p.write_text(s.replace(old, new), encoding="utf-8")


def sub_between(path, start, end, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    a, b = s.index(start), s.index(end)
    p.write_text(s[:a] + new + s[b:], encoding="utf-8")


# ---- markets.py: counts as dict of arrays
sub("src/markets.py",
    '''    counts: optional {"corners"|"cards": (mu_home, mu_away, phi_team, phi_total)} arrays.''',
    '''    counts: optional {"corners"|"cards": {"mh", "ma", "mt": means; "phi_h", "phi_a", "phi_t": spreads}}.''')
sub("src/markets.py",
    '''        mh, ma, ph_team, ph_total = counts[stat]
        mu, phi = {"H": (mh, ph_team), "A": (ma, ph_team), "T": (np.asarray(mh) + np.asarray(ma), ph_total)}[side]''',
    '''        c = counts[stat]
        mu, phi = {"H": (c["mh"], c["phi_h"]), "A": (c["ma"], c["phi_a"]), "T": (c["mt"], c["phi_t"])}[side]''')

# ---- backtest.py
sub_between("src/backtest.py", "def counts_arg(", "def build_counts(", '''def counts_arg(d: pd.DataFrame) -> dict:
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


''')
sub_between("src/backtest.py", "def count_skill(", "def logloss_1x2(", '''def count_skill(bt: pd.DataFrame, won: pd.DataFrame, cal_counts: dict) -> list:
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


''')
sub("src/backtest.py",
    '''    probs = market_probs(lh, la, share, counts_arg(bt))
    won = settle(bt)
    res["count_skill"] = count_skill(bt, won)
''',
    '''    cal_counts, res["count_calibration"] = walk_forward_counts(bt, FIRST_EVAL_SEASON)
    probs = market_probs(lh, la, share, cal_counts)
    won = settle(bt)
    res["count_skill"] = count_skill(bt, won, cal_counts)

    # --- everything below is scored from FIRST_EVAL_SEASON, where corners/cards are out of sample
    ev = (bt["Season"] >= FIRST_EVAL_SEASON).to_numpy()
    bt, probs, won = bt[ev].reset_index(drop=True), probs[ev].reset_index(drop=True), won[ev].reset_index(drop=True)
    res.update({"matches": len(bt), "from": str(bt["Date"].min().date())})
''')
sub("src/backtest.py",
    '''TEST_FROM = pd.Timestamp("2017-07-01")   # leave two seasons of warm-up history''',
    '''TEST_FROM = pd.Timestamp("2017-07-01")   # leave two seasons of warm-up history
FIRST_EVAL_SEASON = 2019   # corners/cards calibration needs two earlier backtest seasons''')

# ---- predict.py: apply latest calibration
sub("src/predict.py",
    "from backtest import REPORT, STATS, add_count_inputs, count_columns, counts_arg",
    "from backtest import REPORT, STATS, add_count_inputs, calibrated_counts, count_columns")
sub("src/predict.py",
    '''    probs = market_probs(lh, la, cfg["first_half_share"], counts_arg(fx))''',
    '''    cc = calibrated_counts(fx, cfg["count_calibration"])
    fx["co_mh"], fx["co_ma"] = cc["corners"]["mh"], cc["corners"]["ma"]
    fx["ca_mh"], fx["ca_ma"] = cc["cards"]["mh"], cc["cards"]["ma"]
    probs = market_probs(lh, la, cfg["first_half_share"], cc)''')

# ---- validate_reasons.py: same walk-forward calibration
sub("src/validate_reasons.py",
    "from backtest import COUNTS, DATA, KEYS, PRED, REPORT, counts_arg",
    "from backtest import COUNTS, DATA, FIRST_EVAL_SEASON, KEYS, PRED, REPORT, walk_forward_counts")
sub("src/validate_reasons.py",
    '''    bt = bt[bt["Season"] >= args.from_season].reset_index(drop=True)
    lh, la = blend(bt["lh_mod"].to_numpy(), bt["la_mod"].to_numpy(), bt["lh_mkt"].to_numpy(), bt["la_mkt"].to_numpy(), cfg["market_weight"])
    probs = market_probs(lh, la, cfg["first_half_share"], counts_arg(bt))''',
    '''    bt = bt.reset_index(drop=True)
    cc, _ = walk_forward_counts(bt, FIRST_EVAL_SEASON)
    keep = (bt["Season"] >= args.from_season).to_numpy()
    bt = bt[keep].reset_index(drop=True)
    cc = {stat: {k: v[keep] for k, v in c.items()} for stat, c in cc.items()}
    lh, la = blend(bt["lh_mod"].to_numpy(), bt["la_mod"].to_numpy(), bt["lh_mkt"].to_numpy(), bt["la_mkt"].to_numpy(), cfg["market_weight"])
    probs = market_probs(lh, la, cfg["first_half_share"], cc)
    bt["co_mh"], bt["co_ma"] = cc["corners"]["mh"], cc["corners"]["ma"]
    bt["ca_mh"], bt["ca_ma"] = cc["cards"]["mh"], cc["cards"]["ma"]''')
print("patched")
