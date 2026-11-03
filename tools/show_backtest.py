"""Print the headline numbers from output/backtest_summary.json."""
import json
from pathlib import Path

import pandas as pd

r = json.loads((Path(__file__).resolve().parent.parent / "output" / "backtest_summary.json").read_text())
print(r["matches"], "matches", r["from"], "to", r["to"])
print(pd.DataFrame(r["count_skill"]).to_string())
print(json.dumps(r["count_calibration"]))
print("by_slot", [(s["slot"], s["pred"], s["hit"]) for s in r["by_slot"]])
print("goals-only extras hit", r["goals_only_extras_hit"], "| all three", r["all_three_hit"])
o = pd.DataFrame(r["by_option"])
agg = o.groupby("category").apply(
    lambda g: pd.Series({"n": g.n.sum(), "pred": (g.pred * g.n).sum() / g.n.sum(), "hit": (g.hit * g.n).sum() / g.n.sum()}),
    include_groups=False)
print(agg.round(4).sort_values("n", ascending=False).to_string())
if "support_check" in r:
    print(pd.DataFrame(r["support_check"]["by_support"]).to_string())
