"""Generate picks (with reasons) for upcoming fixtures.

Fixtures come from football-data.co.uk/fixtures.csv (refreshed by the site before each
round) or from your own CSV with columns Div, Date, HomeTeam, AwayTeam and optionally
AvgH, AvgD, AvgA, Avg>2.5, Avg<2.5 and Referee. Without odds the pure team-rating model is used.

Everything is fitted only on matches before --asof (default: the earliest fixture date),
so running this on past fixtures is a fair out-of-sample check; results are filled in
automatically when they're already in the dataset.

Usage: python src/predict.py [--fixtures my_games.csv] [--asof 2026-10-30] [--no-download]
"""
import argparse
import difflib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import REPORT, STATS, add_count_inputs, calibrated_counts, count_columns
from download import LEAGUES, get_with_retry
from europe import EURO_NAMES
from markets import KEY_INFO, TOP5, market_probs, picks_for, settle
from model import CountRatings, MarketInverter, TeamRatings, blend
from reasons import History, explain

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "data" / "fixtures" / "fixtures.csv"
OUT_DIR = ROOT / "output"
COMP_NAMES = {**LEAGUES, **EURO_NAMES}
RESULT_COLS = ["FTHG", "FTAG", "HTHG", "HTAG", "HC", "AC", "HY", "AY", "HR", "AR"]


def load_fixtures(path: Path, download: bool) -> pd.DataFrame:
    if download and path == FIXTURES:
        r = get_with_retry("https://football-data.co.uk/fixtures.csv")
        if r is not None and r.status_code == 200:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
    fx = pd.read_csv(path, encoding="utf-8-sig")
    fx = fx[fx["Div"].isin(LEAGUES)].copy()
    fx["Date"] = pd.to_datetime(fx["Date"], dayfirst=True)
    for c in ["AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5", "MaxH", "MaxD", "MaxA", "Max>2.5", "Max<2.5", "Time", "Referee"]:
        if c not in fx.columns:
            fx[c] = np.nan
    return fx.reset_index(drop=True)


def check_names(fx, hist):
    """Warn about team names the dataset doesn't know (they get a 'promoted team' rating)."""
    for div, f in fx.groupby("Div"):
        known = set(hist.loc[hist["Div"] == div, "HomeTeam"])
        for t in set(f["HomeTeam"]) | set(f["AwayTeam"]):
            if t not in known:
                sug = difflib.get_close_matches(t, known, n=1)
                print(f"  ! unknown team '{t}' in {div}" + (f" - did you mean '{sug[0]}'?" if sug else ""))


def book_odds(m: pd.Series, key: str) -> tuple[float, float, str]:
    """Real bookmaker prices for a pick from the fixture file: (average, best, note).

    football-data.co.uk lists 1X2 and Over/Under 2.5 prices from several bookmakers. Double
    chance isn't listed, so it is estimated from the 1X2 prices. Other markets have none.
    """
    def dc(a, b):
        return 1 / (1 / a + 1 / b) if a > 0 and b > 0 else np.nan
    g = lambda c: float(m[c]) if c in m and pd.notna(m[c]) else np.nan
    src = {
        "1": (g("AvgH"), g("MaxH"), "bookmakers"), "2": (g("AvgA"), g("MaxA"), "bookmakers"),
        "1X": (dc(g("AvgH"), g("AvgD")), dc(g("MaxH"), g("MaxD")), "estimated from 1X2 prices"),
        "X2": (dc(g("AvgA"), g("AvgD")), dc(g("MaxA"), g("MaxD")), "estimated from 1X2 prices"),
        "O2.5": (g("Avg>2.5"), g("Max>2.5"), "bookmakers"), "U2.5": (g("Avg<2.5"), g("Max<2.5"), "bookmakers"),
    }
    avg, best, note = src.get(key, (np.nan, np.nan, ""))
    return (avg, best, note) if np.isfinite(avg) else (np.nan, np.nan, "")


def predict_fixtures(fx: pd.DataFrame, hist: pd.DataFrame, asof: pd.Timestamp, cfg: dict,
                     inv: MarketInverter) -> list[dict]:
    """Picks (with reasons) for fixtures, fitted only on matches before `asof`.
    Results are attached for any fixture already in `hist`."""
    fx = fx.reset_index(drop=True).copy()
    # goals: team ratings blended with bookmaker-implied expected goals
    fx["lh_mod"], fx["la_mod"] = np.nan, np.nan
    for div, f in fx.groupby("Div"):
        r = TeamRatings().fit(hist[hist["Div"] == div], asof)
        fx.loc[f.index, "lh_mod"], fx.loc[f.index, "la_mod"] = r.predict(f["HomeTeam"].tolist(), f["AwayTeam"].tolist())
    fx["lh_mkt"], fx["la_mkt"] = inv.invert(fx["AvgH"], fx["AvgD"], fx["AvgA"], fx["Avg>2.5"], fx["Avg<2.5"])
    lh, la = blend(fx["lh_mod"].to_numpy(), fx["la_mod"].to_numpy(),
                   fx["lh_mkt"].to_numpy(), fx["la_mkt"].to_numpy(), cfg["market_weight"])
    fx["xg_h"], fx["xg_a"] = lh, la

    # corners & cards
    for div, f in fx.groupby("Div"):
        h = hist[hist["Div"] == div]
        models = {s: CountRatings(use_referee=ref).fit(h, asof, hc, ac) for s, (hc, ac, ref) in STATS.items()}
        for c, v in count_columns(models, f).items():
            fx.loc[f.index, c] = v

    cc = calibrated_counts(fx, cfg["count_calibration"])
    fx["co_mh"], fx["co_ma"] = cc["corners"]["mh"], cc["corners"]["ma"]
    fx["ca_mh"], fx["ca_ma"] = cc["cards"]["mh"], cc["cards"]["ma"]
    probs = market_probs(lh, la, cfg["first_half_share"], cc)
    picks = picks_for(probs, counts_ok=fx["Div"].isin(TOP5).to_numpy())   # corners/cards only in the top 5 leagues
    euro = fx["Div"].isin(EURO_NAMES).to_numpy()
    if euro.any():  # European results come without a half-time score, so no 1st-half picks there
        picks = pd.concat([picks[~euro], picks_for(probs[euro], exclude={"1st Half Over/Under"}, counts_ok=[False] * int(euro.sum()))]).sort_index()

    # attach results if these games have already been played
    keys = ["Div", "Date", "HomeTeam", "AwayTeam"]
    res = fx[keys].merge(hist[keys + RESULT_COLS], on=keys, how="left")
    won = settle(res) if res["FTHG"].notna().any() else None

    past = History(hist, asof)
    rows = []
    for i, m in fx.iterrows():
        extra = {"xg_h": lh[i], "xg_a": la[i], "co_h": m["co_mh"], "co_a": m["co_ma"],
                 "ca_h": m["ca_mh"], "ca_a": m["ca_ma"], "referee": m["Referee"]}
        row = {
            "date": m["Date"].strftime("%Y-%m-%d"), "time": m["Time"] if isinstance(m["Time"], str) else "",
            "div": m["Div"], "league": COMP_NAMES[m["Div"]], "home": m["HomeTeam"], "away": m["AwayTeam"],
            "referee": m["Referee"] if isinstance(m["Referee"], str) else "",
            "xg_home": round(float(lh[i]), 2), "xg_away": round(float(la[i]), 2),
            "p_home": round(float(probs.at[i, "1"]), 3), "p_draw": round(float(1 - probs.at[i, "1"] - probs.at[i, "2"]), 3),
            "p_away": round(float(probs.at[i, "2"]), 3), "odds_used": bool(np.isfinite(fx.at[i, "lh_mkt"])),
            "picks": [],
        }
        for slot, s in enumerate(("pick0", "pick1", "pick2", "pick3")):   # pick0 = the best pick
            k = picks.at[i, s] if s in picks.columns else None
            if not isinstance(k, str):
                continue
            cat, label = KEY_INFO[k]
            p = float(picks.at[i, f"{s}_p"])
            why, support = explain(past, m["HomeTeam"], m["AwayTeam"], k, probs.loc[i], extra)
            avg, best, note = book_odds(m, k)
            pick = {"slot": slot, "key": k, "category": cat, "pick": label, "prob": round(p, 3), "fair_odds": round(1 / p, 2),
                    "book_avg": None if np.isnan(avg) else round(avg, 2),
                    "book_best": None if np.isnan(best) else round(best, 2), "book_note": note,
                    "why": why, "support": support}
            if won is not None and pd.notna(res.at[i, "FTHG"]):
                pick["won"] = bool(won.at[i, k]) if pd.notna(won.at[i, k]) else None
            row["picks"].append(pick)
        if pd.notna(res.at[i, "FTHG"]):
            row["result"] = f"{int(res.at[i, 'FTHG'])}-{int(res.at[i, 'FTAG'])}"
        row["safety"] = row["picks"][0]["prob"] if row["picks"] and row["picks"][0]["slot"] == 0 else 0
        rows.append(row)

    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path, default=FIXTURES)
    ap.add_argument("--asof", type=pd.Timestamp)
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(REPORT.read_text())
    inv = MarketInverter()
    hist = add_count_inputs(pd.read_parquet(ROOT / "data" / "matches.parquet").dropna(subset=["Date"]), inv)
    fx = load_fixtures(args.fixtures, not args.no_download)
    if fx.empty:
        raise SystemExit("No fixtures for the configured leagues.")
    asof = args.asof or fx["Date"].min()
    if args.fixtures == FIXTURES:  # keep this round's list: the next download replaces fixtures.csv
        dated = FIXTURES.with_name(f"fixtures_{asof:%Y-%m-%d}.csv")
        if not dated.exists():
            dated.write_bytes(FIXTURES.read_bytes())
    check_names(fx, hist)

    rows = predict_fixtures(fx, hist, asof, cfg, inv)

    rows.sort(key=lambda r: (r["date"], r["league"], r["time"]))
    OUT_DIR.mkdir(exist_ok=True)
    stamp = asof.strftime("%Y-%m-%d")
    bt_keys = ("matches", "from", "to", "market_weight", "by_option", "by_slot", "cat1_reliability",
               "all_three_hit", "by_league_cat1", "count_skill", "goals_only_extras_hit", "support_check")
    out = {"asof": stamp, "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
           "generated_from": str(args.fixtures.name), "matches": rows,
           "backtest": {k: cfg[k] for k in bt_keys if k in cfg}}
    (OUT_DIR / f"picks_{stamp}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    flat = pd.json_normalize(rows, "picks", ["date", "league", "home", "away", "safety"], errors="ignore")
    flat.to_csv(OUT_DIR / f"picks_{stamp}.csv", index=False)

    print(f"{len(rows)} matches, fitted on data before {stamp}\n")
    for r in sorted(rows, key=lambda r: -r["safety"])[:8]:
        res_s = f"  [{r['result']}]" if "result" in r else ""
        print(f"{r['home']} v {r['away']}{res_s}")
        for p in r["picks"]:
            mark = "" if "won" not in p else (" ✓" if p["won"] else " ✗")
            print(f"   {p['pick']} {p['prob']:.0%} (@{p['fair_odds']}) [{p['support']}]{mark}\n      {p['why']}")
    if any("result" in r for r in rows):
        allp = [p for r in rows for p in r["picks"] if p.get("won") is not None]
        df = pd.DataFrame(allp)
        print("\nResults by market:\n", df.groupby("category").agg(n=("won", "size"), hit=("won", "mean"), pred=("prob", "mean")).round(3).to_string())
        print("\nResults by support:\n", df.groupby("support").agg(n=("won", "size"), hit=("won", "mean"), pred=("prob", "mean")).round(3).to_string())


if __name__ == "__main__":
    main()
