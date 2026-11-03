"""One-off patch: European competitions in predict_fixtures() and the daily update."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sub(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"{path}: {old[:70]!r} found {s.count(old)}x"
    p.write_text(s.replace(old, new), encoding="utf-8")


# ---- predict.py
sub("src/predict.py", "from download import LEAGUES, get_with_retry",
    "from download import LEAGUES, get_with_retry\nfrom europe import EURO_NAMES")
sub("src/predict.py", 'RESULT_COLS = [', 'COMP_NAMES = {**LEAGUES, **EURO_NAMES}\nRESULT_COLS = [')
sub("src/predict.py", '''"div": m["Div"], "league": LEAGUES[m["Div"]],''', '''"div": m["Div"], "league": COMP_NAMES[m["Div"]],''')
sub("src/predict.py", '''    picks = picks_for(probs)
''', '''    picks = picks_for(probs)
    euro = fx["Div"].isin(EURO_NAMES).to_numpy()
    if euro.any():  # European results come without a half-time score, so no 1st-half picks there
        picks = pd.concat([picks[~euro], picks_for(probs[euro], exclude={"1st Half Over/Under"})]).sort_index()
''')

# ---- update.py
sub("src/update.py", "from download import LEAGUES",
    "from download import LEAGUES\nfrom europe import EURO, api_key, europe_fixtures, update_results")
sub("src/update.py", '''def fill_results(log: pd.DataFrame, hist: pd.DataFrame) -> int:
    """Write scores and won/lost for every past pick the dataset now has a result for."""
    played = hist.dropna(subset=["FTHG", "FTAG"]).copy()
    played["date"] = played["Date"].dt.strftime("%Y-%m-%d")''',
    '''def fill_results(log: pd.DataFrame, hist: pd.DataFrame, extra: pd.DataFrame | None = None) -> int:
    """Write scores and won/lost for every past pick the dataset (plus `extra` results,
    e.g. European games) now has a result for."""
    played = hist.dropna(subset=["FTHG", "FTAG"]).copy()
    played["date"] = played["Date"].dt.strftime("%Y-%m-%d")
    if extra is not None and len(extra):
        played = pd.concat([played, extra.assign(date=extra["Date"].astype(str))], ignore_index=True)''')
sub("src/update.py", '''    fx = fx[(fx["Date"] >= today) & (fx["Date"] < today + pd.Timedelta(days=args.days))]
    print(f"\\nWindow {t} + {args.days} days: {len(fx)} fixtures")''',
    '''    fx = fx[(fx["Date"] >= today) & (fx["Date"] < today + pd.Timedelta(days=args.days))]
    print(f"\\nWindow {t} + {args.days} days: {len(fx)} league fixtures")
    key = None if args.no_europe else api_key()
    if key:
        try:
            efx = europe_fixtures(today, args.days, hist, key)
            fx = pd.concat([fx, efx], ignore_index=True) if len(efx) else fx
        except Exception as e:   # a European outage must not stop the league picks
            print(f"  ! European competitions skipped: {e}")
    elif not args.no_europe:
        print("  European competitions skipped: no API key in config/odds_api_key.txt")''')
sub("src/update.py", '''        check_names(fx, hist)''', '''        check_names(fx[~fx["Div"].isin(EURO)], hist)''')
sub("src/update.py", '''    log = merge(load_log(), new, t)
    settled = fill_results(log, hist)''', '''    log = merge(load_log(), new, t)
    euro_results = None
    if key:
        try:
            euro_results = update_results(log, today, hist, key)
        except Exception as e:
            print(f"  ! European results skipped: {e}")
    settled = fill_results(log, hist, euro_results)''')
sub("src/update.py", '''    ap.add_argument("--no-download", action="store_true")''',
    '''    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--no-europe", action="store_true", help="skip The Odds API (saves credits)")''')
print("patched")
