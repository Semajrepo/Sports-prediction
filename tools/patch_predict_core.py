"""One-off patch: move predict.py's core into predict_fixtures() so the daily update can reuse it."""
from pathlib import Path

p = Path(__file__).resolve().parent.parent / "src" / "predict.py"
s = p.read_text(encoding="utf-8")

start = s.index("    # goals: team ratings blended with bookmaker-implied expected goals")
end = s.index("    rows.sort(key=lambda r: (r[\"date\"], r[\"league\"], r[\"time\"]))")
core = s[start:end]

# dedent nothing: the block becomes the body of a new function at the same indentation
func = '''def predict_fixtures(fx: pd.DataFrame, hist: pd.DataFrame, asof: pd.Timestamp, cfg: dict,
                     inv: MarketInverter) -> list[dict]:
    """Picks (with reasons) for fixtures, fitted only on matches before `asof`.
    Results are attached for any fixture already in `hist`."""
    fx = fx.reset_index(drop=True).copy()
''' + core + "    return rows\n\n\n"

new_core_call = '''    rows = predict_fixtures(fx, hist, asof, cfg, inv)

'''
s = s[:start] + new_core_call + s[end:]
s = s.replace("def main():", func + "def main():", 1)

# record the market key and division with every pick, for automatic settling later
old = '''            pick = {"category": cat, "pick": label, "prob": round(p, 3), "fair_odds": round(1 / p, 2),
                    "why": why, "support": support}'''
assert s.count(old) == 1
s = s.replace(old, '''            pick = {"key": k, "category": cat, "pick": label, "prob": round(p, 3), "fair_odds": round(1 / p, 2),
                    "why": why, "support": support}''')
old = '''            "date": m["Date"].strftime("%Y-%m-%d"), "time": m["Time"] if isinstance(m["Time"], str) else "",
            "league": LEAGUES[m["Div"]],'''
assert s.count(old) == 1
s = s.replace(old, '''            "date": m["Date"].strftime("%Y-%m-%d"), "time": m["Time"] if isinstance(m["Time"], str) else "",
            "div": m["Div"], "league": LEAGUES[m["Div"]],''')
p.write_text(s, encoding="utf-8")
print("patched")
