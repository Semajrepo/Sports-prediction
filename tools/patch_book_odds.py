"""One-off patch: attach real bookmaker prices (football-data.co.uk average and best) to picks where they exist."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sub(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"{path}: {old[:70]!r}"
    p.write_text(s.replace(old, new), encoding="utf-8")


# fixtures: keep the best-price columns too
sub("src/predict.py",
    '''    for c in ["AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5", "Time", "Referee"]:''',
    '''    for c in ["AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5", "MaxH", "MaxD", "MaxA", "Max>2.5", "Max<2.5", "Time", "Referee"]:''')

sub("src/predict.py", '''def predict_fixtures(''', '''def book_odds(m: pd.Series, key: str) -> tuple[float, float, str]:
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


def predict_fixtures(''')

sub("src/predict.py",
    '''            pick = {"key": k, "category": cat, "pick": label, "prob": round(p, 3), "fair_odds": round(1 / p, 2),
                    "why": why, "support": support}''',
    '''            avg, best, note = book_odds(m, k)
            pick = {"key": k, "category": cat, "pick": label, "prob": round(p, 3), "fair_odds": round(1 / p, 2),
                    "book_avg": None if np.isnan(avg) else round(avg, 2),
                    "book_best": None if np.isnan(best) else round(best, 2), "book_note": note,
                    "why": why, "support": support}''')

# record: keep the prices with each pick
sub("src/update.py",
    '''                      f"pick{i}_prob": p["prob"], f"pick{i}_odds": p["fair_odds"], f"pick{i}_won": "",''',
    '''                      f"pick{i}_prob": p["prob"], f"pick{i}_odds": p["fair_odds"], f"pick{i}_won": "",
                      f"pick{i}_book_avg": "" if p.get("book_avg") is None else p["book_avg"],
                      f"pick{i}_book_best": "" if p.get("book_best") is None else p["book_best"],
                      f"pick{i}_book_note": p.get("book_note", ""),''')
print("patched")
