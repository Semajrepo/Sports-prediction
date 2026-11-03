"""Slips for SportyBet booking codes: list a slip's picks with where to find them on SportyBet,
and record the code once booked, for the dashboard's "Booking codes" list.

  python src/slip.py                       today's suggested slip (3 safest best picks)
  python src/slip.py --n 5                 the 5 safest
  python src/slip.py --odds 5              safest best picks until about 5 odds (estimated)
  python src/slip.py --date 2026-10-31 --days 2
  python src/slip.py --text "..."          a slip pasted from the dashboard's Copy slip button
  python src/slip.py --record N187HV --odds-real 1.39 --label "Safest 3"   (after booking the slip
                                            last listed; writes output/dashboard/codes.csv)

The suggested slip uses the same rule as the dashboard: one best pick per match, safest first.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
UP = {"football": ROOT / "output" / "dashboard" / "upcoming.csv", "volley": ROOT / "output" / "dashboard" / "volley_upcoming.csv"}
CODES = ROOT / "output" / "dashboard" / "codes.csv"
LAST = ROOT / "output" / "last_slip.json"
SB = 0.95   # SportyBet's price is estimated at about 5% below fair odds


def where(market: str, pick: str) -> str:
    """Which SportyBet tab and market holds a pick, and which button to press."""
    m = re.match(r"(Home|Away) (Corners|Cards) (Over|Under) ([\d.]+)", pick)
    if m:
        side, stat, ou, line = m.groups()
        name = "Total Corners" if stat == "Corners" else "Bookings"
        return f"{'Corners' if stat == 'Corners' else 'Bookings'} tab > '{side} Team {name}' > {ou} {line}"
    m = re.match(r"(Corners|Cards) (Over|Under) ([\d.]+)", pick)
    if m:
        stat, ou, line = m.groups()
        tab = "Corners" if stat == "Corners" else "Bookings"
        return f"{tab} tab > '{tab} - Over/Under' {line} > {ou} {line}"
    table = {
        "1X2 / Double Chance": {"Home": "Main > '1X2' > Home", "Away": "Main > '1X2' > Away",
                                "Home/Draw": "Main > 'Double Chance' > Home or Draw", "Away/Draw": "Main > 'Double Chance' > Draw or Away",
                                "Home/Away": "Main > 'Double Chance' > Home or Away"},
        "GG/NG": {"GG (both teams score)": "Goals > 'GG/NG' > GG", "NG (not both score)": "Goals > 'GG/NG' > NG"},
    }
    if market in table and pick in table[market]:
        return table[market][pick]
    if market == "Over/Under":
        return f"Goals > 'Over/Under' > {pick}"
    if market in ("Home Team Over/Under", "Away Team Over/Under"):
        side, rest = pick.split(" ", 1)
        return f"Goals > '{side} Team Over/Under' > {rest}"
    if market == "1st Half Over/Under":
        return f"Half > '1st Half - Over/Under' > {pick.replace('1st Half ', '')}"
    if market == "Multigoals":
        return f"Goals > 'Multigoals' > {pick.split()[-1]}"
    if market == "Double Chance & Over/Under":
        return f"Main/Goals > 'Double Chance & Over/Under' > {pick}"
    # volleyball
    if market == "Winner":
        return f"Main > 'Winner' > {pick}"
    if market == "Set Handicap":
        return f"Main > 'Set Handicap' (or 'Handicap Sets') > {pick}"
    if market == "Total Sets":
        return f"Main > 'Total Sets' (Over/Under) > {pick}"
    if market == "1st Set Winner":
        return f"Sets > '1st Set - Winner' > {pick}"
    return f"{market} > {pick}"


def suggested(sport: str, date: str, days: int, n: int | None, odds: float | None) -> list[dict]:
    up = pd.read_csv(UP[sport], dtype=str, keep_default_na=False)
    dates = [(pd.Timestamp(date) + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    up = up[up["date"].isin(dates) & (up["pick0"] != "")].copy()
    up["p"] = up["pick0_prob"].astype(float)
    up = up.sort_values(["p", "time"], ascending=[False, True])
    legs, total = [], 1.0
    for _, m in up.iterrows():
        legs.append({"date": m["date"], "time": m["time"], "league": m["league"], "home": m["home"], "away": m["away"],
                     "market": m["pick0_market"], "pick": m["pick0"], "p": m["p"]})
        total *= SB / m["p"]
        if (odds and total >= odds) or (n and len(legs) == n):
            break
    if odds and total < odds:
        return []
    return legs


def from_text(text: str) -> list[dict]:
    """Lines from the dashboard's Copy slip: '1. Home v Away · League · Fri 30 Oct 20:00 · Pick [Market] · 79%'."""
    legs = []
    for line in text.splitlines():
        m = re.match(r"\s*\d+\.\s*(.+?) v (.+?) · (.+?) · (.+?) · (.+?) \[(.+?)\] · (\d+)%", line)
        if m:
            home, away, league, when, pick, market, p = m.groups()
            d = re.match(r"\w+ (\d+ \w+)(?: (\d\d:\d\d))?", when)   # "Sat 31 Oct 13:00"
            day = pd.to_datetime(f"{d.group(1)} {pd.Timestamp.now().year}", format="%d %b %Y") if d else None
            if day is not None and day < pd.Timestamp.now().normalize() - pd.Timedelta(days=180):
                day += pd.DateOffset(years=1)   # a January game copied in December
            legs.append({"date": day.strftime("%Y-%m-%d") if day is not None else when, "time": d.group(2) or "" if d else "", "league": league, "home": home, "away": away,
                         "market": market, "pick": pick, "p": int(p) / 100})
    return legs


def show(legs: list[dict]):
    chance, est = 1.0, 1.0
    for i, l in enumerate(legs, 1):
        chance *= l["p"]
        est *= SB / l["p"]
        print(f"{i}. {l['home']} v {l['away']}  ({l['league']}, {l['date']} {l['time']})")
        print(f"   pick: {l['pick']}  [{l['market']}]  chance {l['p']:.0%}")
        print(f"   on SportyBet: {where(l['market'], l['pick'])}")
    print(f"\n{len(legs)} picks, chance all win {chance:.0%}, about {est:.2f} odds estimated")


def record(code: str, odds_real: float | None, label: str, sport: str):
    legs = json.loads(LAST.read_text(encoding="utf-8")) if LAST.exists() else []
    row = {"made_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "date": legs[0]["date"] if legs else "",
           "sport": sport, "label": label, "code": code, "legs": len(legs),
           "odds": "" if odds_real is None else f"{odds_real:.2f}",
           "chance": f"{pd.Series([l['p'] for l in legs]).prod():.3f}" if legs else "",
           "picks": " | ".join(f"{l['home']} v {l['away']}: {l['pick']}" for l in legs)}
    old = pd.read_csv(CODES, dtype=str, keep_default_na=False) if CODES.exists() else pd.DataFrame()
    out = pd.concat([pd.DataFrame([row]), old], ignore_index=True).head(200)   # newest first
    out.to_csv(CODES, index=False)
    print(f"Recorded {code} ({len(legs)} picks) in {CODES}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=["football", "volley"], default="football")
    ap.add_argument("--date", default=pd.Timestamp.now().strftime("%Y-%m-%d"))
    ap.add_argument("--days", type=int, default=1, choices=[1, 2])
    ap.add_argument("--n", type=int)
    ap.add_argument("--odds", type=float)
    ap.add_argument("--text")
    ap.add_argument("--record")
    ap.add_argument("--odds-real", type=float)
    ap.add_argument("--label", default="Safest 3")
    args = ap.parse_args()
    if args.record:
        record(args.record, args.odds_real, args.label, args.sport)
        return
    legs = from_text(args.text) if args.text else suggested(args.sport, args.date, args.days, args.n or (None if args.odds else 3), args.odds)
    if not legs:
        print("No slip: not enough best picks for that day or target.")
        return
    LAST.write_text(json.dumps(legs), encoding="utf-8")
    show(legs)


if __name__ == "__main__":
    main()
