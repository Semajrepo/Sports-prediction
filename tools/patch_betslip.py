"""One-off patch: round selector, running picks log and a betslip on the dashboard page."""
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "output" / "dashboard" / "index.html"
s = PAGE.read_text(encoding="utf-8")


def sub(old, new):
    global s
    assert s.count(old) == 1, old[:80]
    s = s.replace(old, new)


# ---------------------------------------------------------------- CSS
sub('''  .fp .leg { display: grid; grid-template-columns: 1fr auto auto; gap''',
    '''  .fp .leg { display: grid; grid-template-columns: 1fr auto auto auto; gap''')
sub('''  .fp .grid2 {''', '''  .fp .add { font: inherit; font-size: var(--cds-font-size-body); line-height: 1; width: 2rem; height: 2rem; border-radius: 50%; border: 1px solid var(--color-border-line); background: var(--color-bg); color: var(--color-fg); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
  .fp .add:hover { border-color: var(--color-fg); }
  .fp .add[aria-pressed="true"] { background: var(--color-fg); color: var(--color-bg); border-color: var(--color-fg); }
  .fp .add:focus-visible { outline: 2px solid var(--color-fg); outline-offset: 2px; }
  .fp .made { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); }

  .fp .betslip { position: sticky; bottom: max(var(--cds-gap-sm), env(safe-area-inset-bottom, 0px)); z-index: 3; background: var(--color-panel); border: 1px solid var(--color-fg); border-radius: var(--cds-radius); box-shadow: var(--cds-shadow-popover); padding: var(--cds-pad-sm) var(--cds-pad-md); display: flex; flex-direction: column; gap: var(--cds-gap-xs); }
  .fp .bs-sum { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--cds-gap-xs) var(--cds-gap-md); }
  .fp .bs-sum .bs-title { font-weight: var(--cds-font-weight-medium); }
  .fp .bs-fig { display: inline-flex; align-items: baseline; gap: .35rem; }
  .fp .bs-fig .lbl { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); }
  .fp .bs-fig .v { font-family: var(--font-anthropic-serif); font-size: var(--cds-font-size-heading); font-variant-numeric: tabular-nums; }
  .fp .bs-actions { margin-left: auto; display: flex; gap: var(--cds-gap-xs); }
  .fp .bs-state { font-size: var(--cds-font-size-caption); font-weight: var(--cds-font-weight-medium); }
  .fp .bs-state.won { color: var(--color-ok); } .fp .bs-state.lost { color: var(--color-bad); }
  .fp .bs-list { display: flex; flex-direction: column; max-height: 14rem; overflow: auto; border-top: 1px solid var(--color-border-line); }
  .fp .bs-row { display: grid; grid-template-columns: 1fr auto auto; gap: var(--cds-gap-sm); align-items: center; padding: var(--cds-pad-xs) 0; border-bottom: 1px solid var(--color-border-line); font-size: var(--cds-font-size-caption); }
  .fp .bs-row .m { color: var(--color-fg-muted); }
  .fp .bs-row .o { font-variant-numeric: tabular-nums; }
  .fp .bs-row button { font: inherit; border: 0; background: none; color: var(--color-fg-muted); cursor: pointer; padding: 0 .25rem; }
  .fp .bs-row button:hover { color: var(--color-fg); }
  .fp .bs-note { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); margin: 0; }

  .fp .grid2 {''')

# ---------------------------------------------------------------- markup
sub('''    <p class="note" id="picks-note">Fair odds are the lowest price worth taking: bet only if SportyBet offers that or more.</p>
    <div class="toolbar">
      <label for="league-filter" class="note">League</label>''',
    '''    <p class="note" id="picks-note">Fair odds are the lowest price worth taking: bet only if SportyBet offers that or more. Press + on any pick to add it to your slip.</p>
    <div class="toolbar">
      <label for="round-filter" class="note">Round</label>
      <select id="round-filter"></select>
      <label for="league-filter" class="note">League</label>''')
sub('''      <button class="seg" id="toggle-why" aria-pressed="false">Show all reasons</button>
    </div>
    <div class="slips" id="slips" data-source="picks"></div>''',
    '''      <button class="seg" id="toggle-why" aria-pressed="false">Show all reasons</button>
      <button class="seg" id="add-p1">Add all Pick 1s shown</button>
    </div>
    <div class="slips" id="slips" data-source="picks"></div>
    <div class="betslip" id="betslip" hidden aria-live="polite"></div>''')

# ---------------------------------------------------------------- per-round summary
sub('''dash.calc('weekend_summary', {
  title: 'Picks result for this fixture list',
  description: 'How many of the listed picks have been settled and how many landed.',
  inputs: ['picks'],
  fn: (picks) => {
    const legs = picks.flatMap((m) => [1, 2, 3].map((i) => m[`pick${i}_won`]).filter((w) => w === 'won' || w === 'lost'));
    const p1 = picks.map((m) => m.pick1_won).filter((w) => w === 'won' || w === 'lost');
    return [{
      matches: picks.length,
      legs_settled: legs.length, legs_won: legs.filter((w) => w === 'won').length,
      pick1_settled: p1.length, pick1_won: p1.filter((w) => w === 'won').length,
    }];
  },
});''', '''dash.calc('round_summary', {
  title: 'Results per round',
  description: 'For each round of picks: matches, and how many picks have been settled and landed.',
  inputs: ['picks'],
  fn: (picks) => [...new Set(picks.map((m) => m.round))].map((round) => {
    const rows = picks.filter((m) => m.round === round);
    const done = (w) => w === 'won' || w === 'lost';
    const legs = rows.flatMap((m) => [1, 2, 3].map((i) => m[`pick${i}_won`]).filter(done));
    const p1 = rows.map((m) => m.pick1_won).filter(done);
    return {
      round, matches: rows.length, made: rows[0].made,
      legs_settled: legs.length, legs_won: legs.filter((w) => w === 'won').length,
      pick1_settled: p1.length, pick1_won: p1.filter((w) => w === 'won').length,
    };
  }),
});''')

# ---------------------------------------------------------------- state, round filter, slip
sub('''let leagueSel = '', sortBy = 'safe', showAllWhy = false;''',
    '''let leagueSel = '', sortBy = 'safe', showAllWhy = false, roundSel = null, lastShown = [];
const slip = new Set();      // "match_id|pick number" of each selection on the slip
const roundSelEl = document.getElementById('round-filter');
roundSelEl.addEventListener('change', () => { roundSel = roundSelEl.value; draw(); });
document.getElementById('add-p1').addEventListener('click', () => {
  lastShown.forEach((m) => { if (m.pick1) slip.add(`${m.match_id}|1`); });
  draw();
});
const roundsOf = (rows) => {  // newest round first
  const last = d3.rollup(rows, (v) => d3.max(v, (m) => m.date), (m) => m.round);
  return [...last.keys()].sort((a, b) => last.get(b).localeCompare(last.get(a)));
};''')

# takeaway: the selected round
sub('''  const s = dash.data('weekend_summary'), p = dash.data('picks');
  if (s.status !== 'ok' || p.status !== 'ok' || !s.data.length) { el.innerHTML = '<span class="dash-skeleton">—</span>'; return; }
  const r = s.data[0];
  const dates = p.data.map((m) => m.date).sort();''',
    '''  const s = dash.data('round_summary'), p = dash.data('picks');
  if (s.status !== 'ok' || p.status !== 'ok' || !s.data.length) { el.innerHTML = '<span class="dash-skeleton">—</span>'; return; }
  const rnd = roundSel || roundsOf(p.data)[0];
  const r = s.data.find((x) => x.round === rnd);
  if (!r) {  // "All rounds"
    const tot = (f) => d3.sum(s.data, (x) => x[f]);
    el.textContent = `${num(s.data.length)} rounds, ${num(tot('matches'))} matches so far. Pick 1 landed ${num(tot('pick1_won'))} of ${num(tot('pick1_settled'))} settled; ${num(tot('legs_won'))} of ${num(tot('legs_settled'))} picks overall.`;
    return;
  }
  const dates = p.data.filter((m) => m.round === rnd).map((m) => m.date).sort();''')
sub('''  const b = (field, text) => { const s2 = document.createElement('b'); s2.className = 'num'; s2.setAttribute('data-source', 'weekend_summary'); s2.setAttribute('data-field', field); s2.setAttribute('data-row', '0'); s2.textContent = text; el.append(s2); };
  if (r.pick1_settled > 0) {
    t(`${span}: `); b('pick1_won', num(r.pick1_won)); t(' of '); b('pick1_settled', num(r.pick1_settled));
    t(' Pick 1 slips landed, and '); b('legs_won', num(r.legs_won)); t(' of '); b('legs_settled', num(r.legs_settled));
    t(' picks overall. These were made before kickoff with no knowledge of the results.');''',
    '''  const b = (field, text) => { const s2 = document.createElement('b'); s2.className = 'num'; s2.setAttribute('data-source', 'round_summary'); s2.setAttribute('data-field', field); s2.setAttribute('data-where', `round=${encodeURIComponent(rnd)}`); s2.textContent = text; el.append(s2); };
  if (r.pick1_settled > 0) {
    t(`${span}: `); b('pick1_won', num(r.pick1_won)); t(' of '); b('pick1_settled', num(r.pick1_settled));
    t(' Pick 1 picks landed, and '); b('legs_won', num(r.legs_won)); t(' of '); b('legs_settled', num(r.legs_settled));
    t(r.made === 'back-check'
      ? ' picks overall. This round was a back-check: picks generated after the games, from pre-match data only.'
      : ' picks overall. These were made before kickoff with no knowledge of the results.');''')

# slips: round filter, add buttons
sub('''  const rows = d.data;
  const leagues = [...new Set(rows.map((r) => r.league))].sort();''',
    '''  const rows = d.data;
  const rounds = roundsOf(rows);
  if (roundSel === null) roundSel = rounds[0];
  if (roundSelEl.options.length !== rounds.length + 1) {
    roundSelEl.replaceChildren(...rounds.map((r) => new Option(r, r)), new Option('All rounds', ''));
  }
  roundSelEl.value = roundSel;
  const leagues = [...new Set(rows.map((r) => r.league))].sort();''')
sub('''  let shown = rows.filter((r) => !leagueSel || r.league === leagueSel);''',
    '''  let shown = rows.filter((r) => (!roundSel || r.round === roundSel) && (!leagueSel || r.league === leagueSel));''')
sub('''    ? shown.slice().sort((a, b) => N(b.safety) - N(a.safety))
    : shown.slice().sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));''',
    '''    ? shown.slice().sort((a, b) => N(b.safety) - N(a.safety))
    : shown.slice().sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
  lastShown = shown;''')
sub('''      leg.append(left, prw, od);''',
    '''      const key = `${m.match_id}|${i}`;
      const add = document.createElement('button'); add.className = 'add';
      const on = slip.has(key);
      add.setAttribute('aria-pressed', on);
      add.setAttribute('aria-label', `${on ? 'Remove from' : 'Add to'} slip: ${m.home} v ${m.away}, ${m[`pick${i}`]}`);
      add.textContent = on ? '✓' : '+';
      add.addEventListener('click', () => { if (slip.has(key)) slip.delete(key); else slip.add(key); draw(); });
      leg.append(left, prw, od, add);''')
sub('''  if (!shown.length) box.innerHTML = '<p class="empty">No matches for this league in the current list.</p>';
}''', '''  if (!shown.length) box.innerHTML = '<p class="empty">No matches for this league in this round.</p>';
}

// The slip multiplies the fair odds of every selection, like a bookmaker's accumulator.
function drawBetslip() {
  const el = document.getElementById('betslip');
  const d = dash.data('picks');
  const byId = new Map(d.status === 'ok' ? d.data.map((m) => [m.match_id, m]) : []);
  const sels = [...slip].map((k) => { const [id, i] = k.split('|'); return { k, m: byId.get(id), i }; }).filter((x) => x.m);
  el.hidden = sels.length === 0;
  if (!sels.length) { el.replaceChildren(); return; }
  const odds = sels.reduce((a, x) => a * N(x.m[`pick${x.i}_odds`]), 1);
  const chance = sels.reduce((a, x) => a * N(x.m[`pick${x.i}_prob`]), 1);
  const res = sels.map((x) => x.m[`pick${x.i}_won`]);
  const state = res.includes('lost') ? 'lost' : res.every((w) => w === 'won') ? 'won' : '';
  const sameMatch = sels.length - new Set(sels.map((x) => x.m.match_id)).size;

  const sum = document.createElement('div'); sum.className = 'bs-sum';
  const title = document.createElement('span'); title.className = 'bs-title';
  title.textContent = `Your slip · ${sels.length} pick${sels.length > 1 ? 's' : ''}`;
  const fig = (label, value) => {
    const f = document.createElement('span'); f.className = 'bs-fig';
    const l = document.createElement('span'); l.className = 'lbl'; l.textContent = label;
    const v = document.createElement('span'); v.className = 'v'; v.textContent = value;
    f.append(l, v); return f;
  };
  sum.append(title, fig('Total fair odds', odds.toFixed(2)), fig('Chance all win', pct(chance)));
  if (state) { const st = document.createElement('span'); st.className = `bs-state ${state}`; st.textContent = state === 'won' ? '✓ Slip won' : '✗ Slip lost'; sum.append(st); }
  const actions = document.createElement('span'); actions.className = 'bs-actions';
  const clear = document.createElement('button'); clear.className = 'seg'; clear.textContent = 'Clear slip';
  clear.addEventListener('click', () => { slip.clear(); draw(); });
  actions.append(clear); sum.append(actions);

  const list = document.createElement('div'); list.className = 'bs-list';
  for (const x of sels) {
    const row = document.createElement('div'); row.className = 'bs-row';
    const what = document.createElement('span');
    const mm = document.createElement('span'); mm.className = 'm'; mm.textContent = `${x.m.home} v ${x.m.away} · `;
    const w = x.m[`pick${x.i}_won`];
    what.append(mm, document.createTextNode(x.m[`pick${x.i}`] + (w === 'won' ? ' ✓' : w === 'lost' ? ' ✗' : '')));
    const o = document.createElement('span'); o.className = 'o'; o.textContent = `@${N(x.m[`pick${x.i}_odds`]).toFixed(2)}`;
    const rm = document.createElement('button'); rm.textContent = '✕'; rm.setAttribute('aria-label', `Remove ${x.m[`pick${x.i}`]} from slip`);
    rm.addEventListener('click', () => { slip.delete(x.k); draw(); });
    row.append(what, o, rm); list.append(row);
  }
  const note = document.createElement('p'); note.className = 'bs-note';
  note.textContent = `Take this slip only if SportyBet's total odds are ${odds.toFixed(2)} or more.` +
    (sameMatch ? ' Some picks come from the same match: SportyBet may only allow that in its bet builder, and linked picks make the chance less exact.' : '') +
    ' The chance assumes the picks are independent. The slip clears when the page reloads.';
  el.replaceChildren(sum, list, note);
}''')

sub('''  drawSlips();
  drawReliability();''', '''  drawSlips();
  drawBetslip();
  drawReliability();''')
sub('''<li><b>Reasons:</b>''', '''<li><b>Your slip:</b> press + on picks to build an accumulator. Total fair odds multiply each pick's fair odds; the chance multiplies their probabilities. Compare the total with SportyBet's before placing it.</li>
      <li><b>Reasons:</b>''')
PAGE.write_text(s, encoding="utf-8")
print("patched")
