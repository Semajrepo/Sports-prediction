"""Plain-language reasons for each pick: recent form, head-to-head, team averages, referee.

The pick itself comes from the model. The reason checks how often that exact bet would
have won in each team's recent matches and in past meetings, so it can also disagree:
support is "strong" when every sample backs the pick, "mixed" when one goes against it.
"""
import numpy as np
import pandas as pd

from markets import CAT1, FAMILY, KEY_INFO, settle

FORM_N = 8     # recent matches per team used for "would have won x of last 8"
H2H_N = 6      # most recent head-to-head meetings
REF_N = 20     # referee's most recent games for card averages
SWAP = [("FTHG", "FTAG"), ("HTHG", "HTAG"), ("HC", "AC"), ("HY", "AY"), ("HR", "AR")]
STAT_COLS = [c for pair in SWAP for c in pair]


class History:
    """Past matches indexed by team, pair and referee; only games before `asof` are visible.
    Call set_asof() to move the cut-off (used when checking reasons in the backtest)."""

    def __init__(self, hist: pd.DataFrame, asof: pd.Timestamp):
        h = hist.dropna(subset=["FTHG", "FTAG"]).sort_values("Date")
        h = h[["Date", "Div", "HomeTeam", "AwayTeam", "Referee"] + STAT_COLS].reset_index(drop=True)
        long = pd.concat([h.assign(team=h["HomeTeam"]), h.assign(team=h["AwayTeam"])])
        self.by_team = {t: g.sort_values("Date") for t, g in long.groupby("team")}
        pair = h.assign(pair=[tuple(sorted(x)) for x in zip(h["HomeTeam"], h["AwayTeam"])])
        self.by_pair = {p: g for p, g in pair.groupby("pair")}
        self.by_ref = {r: g for r, g in h.dropna(subset=["Referee", "HY", "AY"]).groupby("Referee")}
        self.set_asof(asof)

    def set_asof(self, asof):
        self.asof = pd.Timestamp(asof)

    def _before(self, g, n):
        if g is None:
            return pd.DataFrame(columns=["Date", "HomeTeam", "AwayTeam"] + STAT_COLS)
        return g.iloc[max(0, g["Date"].searchsorted(self.asof) - n):g["Date"].searchsorted(self.asof)]

    def last(self, team, n=FORM_N):
        return self._before(self.by_team.get(team), n)

    def h2h(self, home, away, n=H2H_N):
        return self._before(self.by_pair.get(tuple(sorted((home, away)))), n)

    def referee(self, ref, n=REF_N):
        if not isinstance(ref, str) or not ref:
            return None
        r = self._before(self.by_ref.get(ref), n)
        if len(r) < 5:
            return None
        return float((r["HY"] + r["AY"] + r["HR"] + r["AR"]).mean()), len(r)


def mirrored(rows, team, slot):
    """Put `team` in the home ('H') or away ('A') slot so a market reads from its side."""
    r = rows.copy()
    flip = (r["AwayTeam"] == team) if slot == "H" else (r["HomeTeam"] == team)
    for a, b in SWAP:
        r.loc[flip, [a, b]] = r.loc[flip, [b, a]].to_numpy()
    return r


def hits(rows, key):
    if rows.empty:
        return 0, 0
    s = settle(rows, only={key})[key].dropna()
    return int(s.sum()), len(s)


def form(rows, team):
    """W/D/L counts from the team's own side, most recent last."""
    m = mirrored(rows, team, "H")
    res = np.where(m["FTHG"] > m["FTAG"], "W", np.where(m["FTHG"] == m["FTAG"], "D", "L"))
    return "".join(res[-5:])


def team_avg(rows, team, col_for):
    """Average of a per-team stat (e.g. HC = corners won) from the team's side."""
    m = mirrored(rows, team, "H").dropna(subset=[col_for])
    return (float(m[col_for].mean()), len(m)) if len(m) else (np.nan, 0)


def match_avg(rows, cols):
    r = rows.dropna(subset=cols)
    return float(r[cols].sum(axis=1).mean()) if len(r) else np.nan


def explain(hist: History, home, away, key, probs: pd.Series, extra: dict) -> tuple[str, str]:
    """Return (reason text, support level) for one pick."""
    cat, label = KEY_INFO[key]
    lh, la = hist.last(home), hist.last(away)
    hh = hist.h2h(home, away)
    samples = [
        (f"{home}'s last {len(lh)}", *hits(mirrored(lh, home, "H"), key)),
        (f"{away}'s last {len(la)}", *hits(mirrored(la, away, "A"), key)),
        ("head-to-heads", *hits(mirrored(hh, home, "H"), key)),
    ]
    used = [(name, k, n) for name, k, n in samples if n >= 3]
    rates = [k / n for _, k, n in used]
    support = "model only" if not rates else "strong" if min(rates) >= 0.7 else "mixed" if min(rates) < 0.5 else "fair"

    parts = []
    if cat == CAT1:
        fh, fa = form(lh, home), form(la, away)
        fav = max(probs["1"], probs["2"])
        side = home if probs["1"] >= probs["2"] else away
        parts.append(f"Form: {home} {fh or 'n/a'}, {away} {fa or 'n/a'} (latest last).")
        parts.append(f"Odds make {side} {fav:.0%} to win, draw {1 - probs['1'] - probs['2']:.0%}.")
    elif FAMILY.get(cat) == "corners":
        ch, nh = team_avg(lh, home, "HC")
        ca, na = team_avg(la, away, "HC")
        if nh and na:
            parts.append(f"{home} win {ch:.1f} corners a game, {away} {ca:.1f} (last {max(nh, na)}).")
        parts.append(f"Expected corners {extra['co_h']:.1f}–{extra['co_a']:.1f}.")
    elif FAMILY.get(cat) == "cards":
        ref = hist.referee(extra.get("referee"))
        if ref:
            parts.append(f"Referee {extra['referee']} averages {ref[0]:.1f} cards a game (last {ref[1]}).")
        cols = ["HY", "AY", "HR", "AR"]
        yh, ya = match_avg(lh, cols), match_avg(la, cols)
        if not (np.isnan(yh) or np.isnan(ya)):
            parts.append(f"Cards per game: {home} matches {yh:.1f}, {away} matches {ya:.1f}.")
        parts.append(f"Expected cards {extra['ca_h']:.1f}–{extra['ca_a']:.1f}.")
    else:
        if cat in ("Home Team Over/Under", "Away Team Over/Under"):
            team, rows, slot = (home, lh, "H") if cat.startswith("Home") else (away, la, "A")
            g, n = team_avg(rows, team, "FTHG")
            c, _ = team_avg(rows, team, "FTAG")
            if n:
                parts.append(f"{team} score {g:.1f} and concede {c:.1f} a game (last {n}).")
        else:
            gh, ga = match_avg(lh, ["FTHG", "FTAG"]), match_avg(la, ["FTHG", "FTAG"])
            if not (np.isnan(gh) or np.isnan(ga)):
                parts.append(f"Goals per game: {home} matches {gh:.1f}, {away} matches {ga:.1f}.")
        parts.append(f"Expected goals {extra['xg_h']:.1f}–{extra['xg_a']:.1f}.")

    if used:
        bits = [f"{k} of {name}" if name != "head-to-heads" else f"{k} of {n} head-to-heads" for name, k, n in used]
        parts.append("Would have won in " + ", ".join(bits[:-1]) + (" and " if len(bits) > 1 else "") + bits[-1] + ".")
    else:
        parts.append("Too little recent history to check it against.")
    if hh.empty:
        parts.append("No meetings in the data since 2015.")
    return " ".join(parts), support
