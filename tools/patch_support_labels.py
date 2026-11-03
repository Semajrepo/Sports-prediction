"""One-off patch: descriptive support labels and the support check by probability band."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sub(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"{path}: {old[:70]!r}"
    p.write_text(s.replace(old, new), encoding="utf-8")


sub("src/export_dashboard.py", '''ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "dashboard"''', '''ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "dashboard"
# The backtest showed these labels don't change the chance of winning beyond the
# probability, so they are shown as plain descriptions, not as safety grades.
SUPPORT_LABEL = {"strong": "History agrees", "fair": "History mostly agrees",
                 "mixed": "History split", "model only": "Little history"}''')
sub("src/export_dashboard.py", '''            r[f"pick{i}_support"] = p.get("support", "")''',
    '''            r[f"pick{i}_support"] = SUPPORT_LABEL.get(p.get("support", ""), "")''')
sub("src/export_dashboard.py", '''    if "support_check" in bt:
        order = {"strong": 0, "fair": 1, "mixed": 2, "model only": 3}
        sc = pd.DataFrame(bt["support_check"]["by_support"]).sort_values("support", key=lambda c: c.map(order))
        sc["support"] = sc["support"].str.capitalize()
        sc[["support", "n", "predicted", "hit_rate"]].to_csv(OUT / "support_check.csv", index=False)''',
    '''    if "support_check" in bt:  # hit rate by probability band (rows) and support label (columns)
        sc = pd.DataFrame(bt["support_check"]["by_band"]).T
        sc = sc.rename(columns={"strong": "agrees", "fair": "mostly_agrees", "mixed": "split"})
        sc.index.name = "band"
        sc[["agrees", "mostly_agrees", "split"]].reset_index().to_csv(OUT / "support_check.csv", index=False)''')

page = "output/dashboard/index.html"
sub(page, '''  .fp .sup.strong { color: var(--color-ok); }
  .fp .sup.mixed { color: var(--color-warn); }
  .fp .sup.fair, .fp .sup.model { color: var(--color-fg-muted); }''', '''  .fp .sup { color: var(--color-fg); }''')
sub(page, '''        const chip = setMark(document.createElement('span'), `pick${i}_support`, m.match_id, sup === 'model only' ? 'Model only' : `${sup[0].toUpperCase()}${sup.slice(1)} support`);
        chip.className = `sup ${sup.split(' ')[0]}`;''', '''        const chip = setMark(document.createElement('span'), `pick${i}_support`, m.match_id, `${sup}.`);
        chip.className = 'sup';''')
sub(page, '''      <p class="note" id="support-note">Every pick from the last two seasons, labelled using only matches played before it. If strong-support picks land more often than their probability says, the label adds information.</p>
      <div class="tbl-wrap">
        <table id="support-table" data-source="support_check" data-row-key="support">
          <thead><tr><th data-field="support">Support</th><th class="r" data-field="n">Picks</th><th class="r" data-field="predicted">Predicted</th><th class="r" data-field="hit_rate">Landed</th></tr></thead>''',
    '''      <p class="note" id="support-note">Every pick from Aug 2024 to now, labelled using only matches played before it. At the same probability, picks land at about the same rate whatever recent history says. Trust the percentage; the reasons explain a pick but don't make it safer.</p>
      <div class="tbl-wrap">
        <table id="support-table" data-source="support_check" data-row-key="band">
          <thead><tr><th data-field="band">Probability</th><th class="r" data-field="agrees">History agrees</th><th class="r" data-field="mostly_agrees">Mostly agrees</th><th class="r" data-field="split">History split</th></tr></thead>''')
sub(page, '''  drawTable('support-table', 'support_check', [['support'], ['n', num, () => 'r'], ['predicted', pct1, () => 'r'], ['hit_rate', pct1, () => 'r']]);''',
    '''  drawTable('support-table', 'support_check', [['band'], ['agrees', pct1, () => 'r'], ['mostly_agrees', pct1, () => 'r'], ['split', pct1, () => 'r']]);''')
sub(page, '''<h2>Does the support label help?</h2>''', '''<h2>Does recent history make a pick safer?</h2>''')
sub(page, '''<b>Strong support</b> means it won at least 70% of the time in every sample; <b>mixed</b> means at least one sample went against it (under 50%); <b>model only</b> means too little history.</li>''',
    '''<b>History agrees</b> means it won at least 70% of the time in every sample; <b>history split</b> means at least one sample went against it (under 50%). Tested over two seasons, this label did not change how often picks landed, so use it as context, not as a safety grade.</li>''')
print("patched")
