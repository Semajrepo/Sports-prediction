// Stand-in for the Claude dashboard runtime, so index.html runs as a plain web page.
// Provides the parts of `dash` the page uses (data, onData, colors, setLink) and loads
// each dataset from <id>.csv next to this file. Needs d3 v7 loaded first.
(function () {
  const cache = {};
  const listeners = [];
  const notify = () => listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });

  function load(id) {
    cache[id] = { status: 'loading', data: [], columns: [], message: '', refreshing: false, meta: [] };
    d3.csv(`${id}.csv`, { cache: 'no-cache' })
      .then((rows) => { cache[id] = { status: 'ok', data: rows, rows, columns: rows.columns || [], message: '', refreshing: false, meta: [] }; })
      .catch((e) => { cache[id] = { status: 'error', data: [], rows: [], columns: [], message: String(e), refreshing: false, meta: [] }; })
      .finally(notify);
  }

  const dark = () => matchMedia('(prefers-color-scheme: dark)').matches;
  const LIGHT = ['#2a78d6', '#d97a1e', '#2f9e6b', '#c2456b', '#7a5fd1', '#8a8f2a', '#1f9bb0', '#a0612b'];
  const DARK = ['#5aa2f0', '#f0a050', '#52c493', '#e7779a', '#a48ef0', '#c1c650', '#4fc4d8', '#d39060'];

  window.dash = {
    data(id) { if (!cache[id]) load(id); return cache[id]; },
    onData(fn) { listeners.push(fn); fn(); },
    get colors() { return dark() ? DARK : LIGHT; },
    setLink(name) { history.replaceState(null, '', `#${name}`); },
    refresh(id) { load(id); },
    params() { return {}; }, setParams() {}, resetParams() {},
  };

  let w = innerWidth;
  addEventListener('resize', () => { if (innerWidth !== w) { w = innerWidth; notify(); } });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', notify);
})();
