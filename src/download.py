"""Download historical match data from football-data.co.uk and merge into one table.

Usage: python src/download.py [--first 2015] [--last 2026]
Season "2026" means 2026/27 (the current, in-progress season).
"""
import argparse
import io
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "matches.parquet"

LEAGUES = {
    # Top 5
    "E0": "England Premier League",
    "SP1": "Spain La Liga",
    "I1": "Italy Serie A",
    "D1": "Germany Bundesliga",
    "F1": "France Ligue 1",
    # English lower tiers
    "E1": "England Championship",
    "E2": "England League One",
    "E3": "England League Two",
    # Other European
    "N1": "Netherlands Eredivisie",
    "P1": "Portugal Primeira Liga",
    "B1": "Belgium Pro League",
    "T1": "Turkey Super Lig",
    "G1": "Greece Super League",
    "SC0": "Scotland Premiership",
}

# Columns kept from the raw files. Closing odds (PSC*/AvgC*) are the benchmark;
# pre-match averages (Avg*) are what a bettor could realistically get.
KEEP = [
    "Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "HTHG", "HTAG",
    "HxG", "AxG", "HS", "AS", "HST", "AST", "HC", "AC",
    "HF", "AF", "HY", "AY", "HR", "AR", "Referee",
    "PSH", "PSD", "PSA", "PSCH", "PSCD", "PSCA",
    "AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA",
    "MaxH", "MaxD", "MaxA",
    "BbAvH", "BbAvD", "BbAvA", "BbAv>2.5", "BbAv<2.5",  # older seasons use Bb* names
    "Avg>2.5", "Avg<2.5", "AvgC>2.5", "AvgC<2.5",
]


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def get_with_retry(url: str, tries: int = 6):
    """The site (or local DNS) drops connections now and then; back off and retry."""
    for attempt in range(tries):
        try:
            return requests.get(url, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
    return None


def fetch(div: str, start_year: int, refresh: bool) -> pd.DataFrame | None:
    code = season_code(start_year)
    path = RAW / f"{div}_{code}.csv"
    if refresh or not path.exists():
        url = f"https://football-data.co.uk/mmz4281/{code}/{div}.csv"
        r = get_with_retry(url)
        if r is None or r.status_code != 200 or len(r.content) < 200:
            return None
        path.write_bytes(r.content)
        time.sleep(0.3)
    try:  # newer files are UTF-8 with a BOM, older ones latin-1
        df = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    df = df.dropna(subset=["HomeTeam", "AwayTeam"])
    df = df[[c for c in KEEP if c in df.columns]].copy()
    df["Season"] = start_year
    return df


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    # Older files have Bb* averages instead of Avg*
    for s in ["H", "D", "A", ">2.5", "<2.5"]:
        if f"BbAv{s}" in df.columns:
            df[f"Avg{s}"] = df[f"Avg{s}"].fillna(df[f"BbAv{s}"])
    df = df.drop(columns=[c for c in df.columns if c.startswith("BbAv")])
    df["League"] = df["Div"].map(LEAGUES)
    return df.sort_values(["Date", "Div"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=2015)
    ap.add_argument("--last", type=int, default=2026)
    ap.add_argument("--refresh-current", action="store_true", default=True)
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)

    frames = []
    for div in LEAGUES:
        for y in range(args.first, args.last + 1):
            refresh = args.refresh_current and y == args.last
            df = fetch(div, y, refresh)
            if df is None:
                print(f"  missing {div} {season_code(y)}")
                continue
            frames.append(df)
        print(f"{div:4s} {LEAGUES[div]}: done")

    all_df = normalise(pd.concat(frames, ignore_index=True))
    all_df.to_parquet(OUT, index=False)
    played = all_df["FTR"].notna().sum()
    print(f"\nSaved {len(all_df):,} rows ({played:,} played) -> {OUT.relative_to(ROOT)}")
    print(all_df.groupby("League")["Season"].agg(["min", "max", "count"]))


if __name__ == "__main__":
    main()
