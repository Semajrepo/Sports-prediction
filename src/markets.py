"""SportyBet-style markets derived from expected goals, corners and cards, plus the pick rules.

Category 1 is always "1X2 / Double Chance" (Home, Away, Home/Draw, Away/Draw).
Two extra picks come from two *different* other categories, choosing the safest
option in each that still pays something (probability capped at P_MAX). At most one
of the two extra picks is a corners market and at most one is a cards market.
"""
import numpy as np
import pandas as pd

from model import MAX_GOALS, count_over_prob, score_matrix

CAT1 = "1X2 / Double Chance"
WIN_THRESHOLD = 0.65   # take a straight Home/Away win only when at least this likely
P_MAX = 0.85           # ignore near-certain options (fair odds below ~1.18 aren't worth betting)
P_MIN = 0.55           # don't recommend an extra pick below this probability

_g = np.arange(MAX_GOALS + 1)
I, J = np.meshgrid(_g, _g, indexing="ij")   # I = home goals, J = away goals

# Goal markets: (key, category, label, scope, condition on home goals i / away goals j)
MARKETS = [
    ("1", CAT1, "Home", "FT", lambda i, j: i > j),
    ("2", CAT1, "Away", "FT", lambda i, j: i < j),
    ("1X", CAT1, "Home/Draw", "FT", lambda i, j: i >= j),
    ("X2", CAT1, "Away/Draw", "FT", lambda i, j: i <= j),
    ("GG", "GG/NG", "GG (both teams score)", "FT", lambda i, j: (i > 0) & (j > 0)),
    ("NG", "GG/NG", "NG (not both score)", "FT", lambda i, j: (i == 0) | (j == 0)),
]
for line in (0.5, 1.5, 2.5, 3.5, 4.5):
    MARKETS += [
        (f"O{line}", "Over/Under", f"Over {line}", "FT", lambda i, j, l=line: i + j > l),
        (f"U{line}", "Over/Under", f"Under {line}", "FT", lambda i, j, l=line: i + j < l),
    ]
for line in (0.5, 1.5, 2.5):
    MARKETS += [
        (f"HO{line}", "Home Team Over/Under", f"Home Over {line}", "FT", lambda i, j, l=line: i > l),
        (f"HU{line}", "Home Team Over/Under", f"Home Under {line}", "FT", lambda i, j, l=line: i < l),
        (f"AO{line}", "Away Team Over/Under", f"Away Over {line}", "FT", lambda i, j, l=line: j > l),
        (f"AU{line}", "Away Team Over/Under", f"Away Under {line}", "FT", lambda i, j, l=line: j < l),
    ]
for line in (0.5, 1.5):
    MARKETS += [
        (f"1HO{line}", "1st Half Over/Under", f"1st Half Over {line}", "1H", lambda i, j, l=line: i + j > l),
        (f"1HU{line}", "1st Half Over/Under", f"1st Half Under {line}", "1H", lambda i, j, l=line: i + j < l),
    ]

# More SportyBet markets
MARKETS.append(("12", CAT1, "Home/Away", "FT", lambda i, j: i != j))          # double chance 12: no draw
for lo, hi in ((1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (2, 3), (2, 4), (2, 5), (2, 6), (3, 4), (3, 5), (3, 6)):
    MARKETS.append((f"MG{lo}-{hi}", "Multigoals", f"Multigoals {lo}-{hi}", "FT",
                    lambda i, j, a=lo, b=hi: (i + j >= a) & (i + j <= b)))
for dc, name, cond in (("1X", "Home/Draw", lambda i, j: i >= j), ("X2", "Away/Draw", lambda i, j: i <= j),
                       ("12", "Home/Away", lambda i, j: i != j)):
    for line in (1.5, 2.5, 3.5, 4.5):
        MARKETS += [
            (f"{dc}&O{line}", "Double Chance & Over/Under", f"{name} & Over {line}", "FT",
             lambda i, j, c=cond, l=line: c(i, j) & (i + j > l)),
            (f"{dc}&U{line}", "Double Chance & Over/Under", f"{name} & Under {line}", "FT",
             lambda i, j, c=cond, l=line: c(i, j) & (i + j < l)),
        ]

# Corners and cards: (key, category, label, stat, side H/A/T, line, is_over)
# Cards count yellows + reds, one each.
COUNT_LINES = {
    ("corners", "T"): ("Total Corners", "Corners", (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)),
    ("corners", "H"): ("Home Team Corners", "Home Corners", (2.5, 3.5, 4.5, 5.5, 6.5, 7.5)),
    ("corners", "A"): ("Away Team Corners", "Away Corners", (1.5, 2.5, 3.5, 4.5, 5.5, 6.5)),
    ("cards", "T"): ("Total Cards", "Cards", (1.5, 2.5, 3.5, 4.5, 5.5, 6.5)),
    ("cards", "H"): ("Home Team Cards", "Home Cards", (0.5, 1.5, 2.5, 3.5)),
    ("cards", "A"): ("Away Team Cards", "Away Cards", (0.5, 1.5, 2.5, 3.5)),
}
COUNT_MARKETS = []
for (stat, side), (cat, name, lines) in COUNT_LINES.items():
    for line in lines:
        tag = f"{stat[:2].upper()}{side}{line}"   # e.g. COT9.5 = total corners 9.5
        COUNT_MARKETS += [(f"{tag}O", cat, f"{name} Over {line}", stat, side, line, True),
                          (f"{tag}U", cat, f"{name} Under {line}", stat, side, line, False)]

KEY_INFO = {k: (cat, label) for k, cat, label, *_ in MARKETS + COUNT_MARKETS}
FAMILY = {cat: stat for _, cat, _, stat, *_ in COUNT_MARKETS}   # category -> "corners"/"cards"

# Actual counts per side, from the match data columns
ACTUAL = {
    ("corners", "H"): lambda d: d["HC"], ("corners", "A"): lambda d: d["AC"],
    ("cards", "H"): lambda d: d["HY"] + d["HR"], ("cards", "A"): lambda d: d["AY"] + d["AR"],
}


def market_probs(lh, la, first_half_share, counts=None) -> pd.DataFrame:
    """Probability of every market for each match (rows).

    counts: optional {"corners"|"cards": {"mh", "ma", "mt": means; "phi_h", "phi_a", "phi_t": spreads}}.
    """
    ft = score_matrix(lh, la)
    h1 = score_matrix(np.asarray(lh) * first_half_share, np.asarray(la) * first_half_share, rho=0.0)
    out = {}
    for key, _, _, scope, cond in MARKETS:
        m = ft if scope == "FT" else h1
        out[key] = (m * cond(I, J)).sum(axis=(1, 2))
    for key, _, _, stat, side, line, is_over in COUNT_MARKETS:
        if not counts or stat not in counts:
            out[key] = np.full(len(out["1"]), np.nan)
            continue
        c = counts[stat]
        mu, phi = {"H": (c["mh"], c["phi_h"]), "A": (c["ma"], c["phi_a"]), "T": (c["mt"], c["phi_t"])}[side]
        p_over = count_over_prob(mu, phi, line)
        out[key] = p_over if is_over else 1 - p_over
    return pd.DataFrame(out)


def settle(df: pd.DataFrame, only=None) -> pd.DataFrame:
    """1.0 won / 0.0 lost / NaN unsettled for every market (or just `only`), from actual
    FT/HT scores, corners and cards."""
    hg, ag = df["FTHG"].to_numpy(), df["FTAG"].to_numpy()
    h1, a1 = df["HTHG"].to_numpy(), df["HTAG"].to_numpy()
    out = {}
    for key, _, _, scope, cond in MARKETS:
        if only is None or key in only:
            out[key] = cond(hg, ag) if scope == "FT" else cond(h1, a1)
    res = pd.DataFrame(out, index=df.index).astype(float)
    for key, _, _, scope, _ in MARKETS:
        if scope == "1H" and key in res:
            res.loc[df["HTHG"].isna(), key] = np.nan
    for key, _, _, stat, side, line, is_over in COUNT_MARKETS:
        if only is not None and key not in only:
            continue
        if any(c not in df for c in ("HC", "AC", "HY", "AY", "HR", "AR")):
            res[key] = np.nan
            continue
        n = ACTUAL[(stat, "H")](df) + ACTUAL[(stat, "A")](df) if side == "T" else ACTUAL[(stat, side)](df)
        res[key] = np.where(n.isna(), np.nan, (n > line) if is_over else (n < line)).astype(float)
    return res


def pick_cat1(p: pd.Series) -> str:
    """Straight win if confident enough, otherwise the safer double chance."""
    if max(p["1"], p["2"]) >= WIN_THRESHOLD:
        return "1" if p["1"] >= p["2"] else "2"
    return "1X" if p["1X"] >= p["X2"] else "X2"


def pick_extras(p: pd.Series, n=2, p_max=P_MAX, p_min=P_MIN, exclude=()) -> list[str]:
    """Safest playable option in each non-Cat1 category; return the top-n categories,
    with at most one corners and one cards pick. `exclude` drops whole categories."""
    best = {}
    for key, (cat, _) in KEY_INFO.items():
        if cat == CAT1 or cat in exclude or not (p_min <= p[key] <= p_max):
            continue
        if cat not in best or p[key] > p[best[cat]]:
            best[cat] = key
    chosen, used = [], set()
    for k in sorted(best.values(), key=lambda k: -p[k]):
        fam = FAMILY.get(KEY_INFO[k][0])
        if fam and fam in used:
            continue
        chosen.append(k)
        used.add(fam)
        if len(chosen) == n:
            break
    return chosen


TOP5 = {"E0", "SP1", "I1", "D1", "F1"}   # corners and cards picks only here: SportyBet offers them on these games
BEST_MAX = 0.79   # best pick: safest option up to 79% (fair odds 1.27+, about 1.20+ on SportyBet; wins about 79%)


def best_pick(p: pd.Series, counts_ok: bool, p_max=BEST_MAX) -> str | None:
    """The single safest pick for a match, from every market (corners/cards only if counts_ok)."""
    best = None
    for key, (cat, _) in KEY_INFO.items():
        v = p[key]
        if (not counts_ok and cat in FAMILY) or not (v <= p_max):
            continue
        if best is None or v > p[best]:
            best = key
    return best


def picks_for(probs: pd.DataFrame, exclude=(), counts_ok=None) -> pd.DataFrame:
    """One row per match: the best pick, then the cat-1 pick plus up to two extra picks.
    counts_ok: per-row booleans allowing corners/cards picks (default: allowed everywhere)."""
    rows = []
    for n_row, (idx, p) in enumerate(probs.iterrows()):
        ok = True if counts_ok is None else bool(counts_ok[n_row])
        ex = set(exclude) | (set() if ok else set(FAMILY))
        b = best_pick(p, ok and not (set(FAMILY) <= set(exclude)))
        row = {"pick0": b, "pick0_p": p[b] if b else None}
        c1 = pick_cat1(p)
        row.update({"pick1": c1, "pick1_p": p[c1]})
        for n, k in enumerate(pick_extras(p, exclude=ex), start=2):
            row[f"pick{n}"], row[f"pick{n}_p"] = k, p[k]
        rows.append(row)
    return pd.DataFrame(rows, index=probs.index)
