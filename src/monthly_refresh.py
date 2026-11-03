"""Monthly refresh: rebuild everything that the daily update doesn't recompute.

The daily update retrains team ratings on every new result, but these were computed once:
the walk-forward backtest and its calibration (market weight, 1st-half share, corners/cards
shrink), the support-label check, the long-run league table and the test history. This
reruns them on all data up to now, then rewrites the dashboard files. About 45 minutes.

Usage: python src/monthly_refresh.py [--skip-reasons]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "output" / "backtest_summary.json"


def run(step: str, *args: str):
    t = time.time()
    print(f"\n== {step}", flush=True)
    subprocess.run([sys.executable, "-u", str(ROOT / "src" / args[0]), *args[1:]], check=True, cwd=ROOT)
    print(f"   done in {(time.time() - t) / 60:.1f} min", flush=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-reasons", action="store_true", help="skip the 20-minute support-label check")
    args = ap.parse_args()
    before = json.loads(REPORT.read_text()) if REPORT.exists() else {}

    run("Download the latest results", "download.py")
    run("Walk-forward backtest and calibration (refit)", "backtest.py", "--refit")
    if not args.skip_reasons:
        run("Support-label check", "validate_reasons.py")
    run("Long-run results per league and season", "build_league_trends.py")
    run("Test history", "build_test_history.py")
    run("Dashboard files", "update.py", "--no-download", "--no-europe", "--no-results90")

    after = json.loads(REPORT.read_text())
    print("\n== What changed")
    print(f"   backtest matches: {before.get('matches')} -> {after.get('matches')} (to {after.get('to')})")
    b0, b1 = before.get("best_pick", {}), after.get("best_pick", {})
    print(f"   best pick won: {b0.get('hit')} -> {b1.get('hit')} (predicted {b1.get('pred')})")
    for k in ("corners_T", "cards_T"):
        c0, c1 = before.get("count_calibration", {}).get(k, {}), after.get("count_calibration", {}).get(k, {})
        print(f"   {k} shrink {c0.get('shrink')} -> {c1.get('shrink')}, spread {c0.get('phi')} -> {c1.get('phi')}")


if __name__ == "__main__":
    main()
