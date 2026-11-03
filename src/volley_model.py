"""Volleyball model: team strength per rally -> chance of winning a set -> every match market.

Each team gets a rating fitted on points won and lost (a rally-level logistic model, recent
games weighted more, plus a league level so a new team starts at its league's average). For a
match, the home side's chance of winning a rally q gives its chance of winning a set to 25 (or
the 5th set to 15) exactly, and from that every set-score of the best-of-5 match.

Two calibration numbers, fitted on a past season (walk-forward):
  shrink   pulls each set's chance toward 50% (sets are less predictable than rallies imply)
  spread   uncertainty about q for the whole match (more 3-0s and 0-3s than independent sets give)
"""
from math import comb

import numpy as np
import pandas as pd
from scipy.optimize import minimize

HALF_LIFE_DAYS = 180
GH_X, GH_W = np.polynomial.hermite_e.hermegauss(9)   # nodes/weights for averaging over a normal
GH_W = GH_W / GH_W.sum()


def set_win(q, to: int):
    """Chance of winning a set to `to` points (win by 2) when each rally is won with chance q."""
    q = np.asarray(q, float)
    r = 1 - q
    p = sum(comb(to - 1 + k, k) * q ** to * r ** k for k in range(to - 1))
    deuce = comb(2 * (to - 1), to - 1) * q ** (to - 1) * r ** (to - 1)
    return p + deuce * q * q / (q * q + r * r)


def logit(p):
    return np.log(p / (1 - p))


def expit(x):
    return 1 / (1 + np.exp(-x))


def set_scores(p, p5):
    """Chance of each final set score (home-away) given set chances p (sets 1-4) and p5 (5th set)."""
    a = 1 - p
    return {
        "3-0": p ** 3, "3-1": 3 * p ** 3 * a, "3-2": 6 * p ** 2 * a ** 2 * p5,
        "0-3": a ** 3, "1-3": 3 * a ** 3 * p, "2-3": 6 * p ** 2 * a ** 2 * (1 - p5),
    }


# Markets: (key, category, label, condition on final sets won h / a, or "S1" for the 1st set)
MARKETS = [
    ("1", "Winner", "Home", lambda h, a: h > a),
    ("2", "Winner", "Away", lambda h, a: a > h),
    ("H-1.5", "Set Handicap", "Home -1.5 sets", lambda h, a: h - a >= 2),
    ("A+1.5", "Set Handicap", "Away +1.5 sets", lambda h, a: h - a < 2),
    ("A-1.5", "Set Handicap", "Away -1.5 sets", lambda h, a: a - h >= 2),
    ("H+1.5", "Set Handicap", "Home +1.5 sets", lambda h, a: a - h < 2),
    ("H-2.5", "Set Handicap", "Home -2.5 sets (3-0)", lambda h, a: h - a == 3),
    ("A+2.5", "Set Handicap", "Away +2.5 sets (wins a set)", lambda h, a: h - a < 3),
    ("A-2.5", "Set Handicap", "Away -2.5 sets (0-3)", lambda h, a: a - h == 3),
    ("H+2.5", "Set Handicap", "Home +2.5 sets (wins a set)", lambda h, a: a - h < 3),
    ("O3.5", "Total Sets", "Over 3.5 sets", lambda h, a: h + a > 3.5),
    ("U3.5", "Total Sets", "Under 3.5 sets (3-0 or 0-3)", lambda h, a: h + a < 3.5),
    ("O4.5", "Total Sets", "Over 4.5 sets (goes to 5)", lambda h, a: h + a > 4.5),
    ("U4.5", "Total Sets", "Under 4.5 sets", lambda h, a: h + a < 4.5),
    ("S1-1", "1st Set Winner", "Home wins 1st set", "S1"),
    ("S1-2", "1st Set Winner", "Away wins 1st set", "S1"),
]
KEY_INFO = {k: (cat, label) for k, cat, label, _ in MARKETS}
SCORES = [(3, 0), (3, 1), (3, 2), (0, 3), (1, 3), (2, 3)]


def market_probs(q, shrink=1.0, spread=0.0) -> pd.DataFrame:
    """Probability of every market, for an array of home rally chances q."""
    q = np.atleast_1d(np.asarray(q, float))
    acc = {k: np.zeros(len(q)) for k in KEY_INFO}
    for x, w in zip(GH_X, GH_W):
        qq = expit(logit(q) + spread * x)
        p = expit(shrink * logit(set_win(qq, 25)))
        p5 = expit(shrink * logit(set_win(qq, 15)))
        sc = set_scores(p, p5)
        for key, _, _, cond in MARKETS:
            if cond == "S1":
                acc[key] += w * (p if key == "S1-1" else 1 - p)
            else:
                acc[key] += w * sum(sc[f"{h}-{a}"] for h, a in SCORES if cond(h, a))
    return pd.DataFrame(acc)


def settle(df: pd.DataFrame) -> pd.DataFrame:
    """1.0 won / 0.0 lost / NaN unknown for every market, from final sets and the 1st set's points."""
    h, a = df["hs"].to_numpy(float), df["as"].to_numpy(float)
    ok = np.isin(np.maximum(h, a), [3]) & (np.minimum(h, a) <= 2)
    out = {}
    for key, _, _, cond in MARKETS:
        if cond == "S1":
            s1 = df["s1h"].to_numpy(float) > df["s1a"].to_numpy(float)
            v = (s1 if key == "S1-1" else ~s1).astype(float)
            v[df["s1h"].isna().to_numpy()] = np.nan
        else:
            v = cond(h, a).astype(float)
        v[~ok] = np.nan
        out[key] = v
    return pd.DataFrame(out, index=df.index)


def finished(games: pd.DataFrame) -> pd.DataFrame:
    """Finished games with a normal best-of-5 result."""
    g = games[(games["status"] == "FT") & games["hs"].notna()].copy()
    g = g[(np.maximum(g["hs"], g["as"]) == 3) & (np.minimum(g["hs"], g["as"]) <= 2)]
    pts = [f"s{i}{s}" for i in range(1, 6) for s in "ha"]
    g["ph"] = g[[c for c in pts if c.endswith("h")]].sum(axis=1, min_count=1)
    g["pa"] = g[[c for c in pts if c.endswith("a")]].sum(axis=1, min_count=1)
    return g


class Ratings:
    """Rally-level ratings: logit(home wins a rally) = home + league[home] + team[home] - league[away] - team[away]."""

    def __init__(self, ridge_team=4.0, ridge_league=1.0):
        self.ridge_team, self.ridge_league = ridge_team, ridge_league

    def fit(self, g: pd.DataFrame, asof: pd.Timestamp):
        g = g[(pd.to_datetime(g["date"]) < asof) & g["ph"].notna()]
        age = (asof - pd.to_datetime(g["date"])).dt.days.to_numpy()
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        self.team_league = self._home_league(g)
        teams = sorted(set(g["home_id"]) | set(g["away_id"]))
        leagues = sorted(set(self.team_league.values()))
        ti = {t: i for i, t in enumerate(teams)}
        li = {l: i for i, l in enumerate(leagues)}
        nt, nl = len(teams), len(leagues)
        hi = g["home_id"].map(ti).to_numpy()
        ai = g["away_id"].map(ti).to_numpy()
        hl = g["home_id"].map(lambda t: li[self.team_league[t]]).to_numpy()
        al = g["away_id"].map(lambda t: li[self.team_league[t]]).to_numpy()
        won, lost = g["ph"].to_numpy(float), g["pa"].to_numpy(float)
        n = won + lost

        def f(x):
            home, lg, tm = x[0], x[1:1 + nl], x[1 + nl:]
            eta = home + lg[hl] + tm[hi] - lg[al] - tm[ai]
            p = expit(eta)
            ll = w * (won * np.log(p) + lost * np.log(1 - p))
            r = w * (won - n * p)   # d ll / d eta
            grad = np.zeros_like(x)
            grad[0] = r.sum()
            np.add.at(grad, 1 + hl, r)
            np.add.at(grad, 1 + al, -r)
            np.add.at(grad, 1 + nl + hi, r)
            np.add.at(grad, 1 + nl + ai, -r)
            pen = self.ridge_league * (lg ** 2).sum() + self.ridge_team * (tm ** 2).sum()
            grad[1:1 + nl] -= 2 * self.ridge_league * lg
            grad[1 + nl:] -= 2 * self.ridge_team * tm
            return -(ll.sum() - pen) / 1000, -grad / 1000

        res = minimize(f, np.zeros(1 + nl + nt), jac=True, method="L-BFGS-B")
        x = res.x
        self.home = x[0]
        self.league = dict(zip(leagues, x[1:1 + nl]))
        self.team = dict(zip(teams, x[1 + nl:]))
        self.games_seen = pd.concat([g["home_id"], g["away_id"]]).value_counts().to_dict()
        return self

    @staticmethod
    def _home_league(g):
        """Each team's domestic league: where it plays most, cups and Champions League aside."""
        dom = g[g["league"] != "CL"]
        both = pd.concat([dom[["home_id", "league"]].rename(columns={"home_id": "t"}),
                          dom[["away_id", "league"]].rename(columns={"away_id": "t"})])
        out = both.groupby("t")["league"].agg(lambda s: s.value_counts().index[0]).to_dict()
        for t in set(g["home_id"]) | set(g["away_id"]):
            out.setdefault(t, "CL")
        return out

    def strength(self, team_id, league: str) -> float:
        lg = self.team_league.get(team_id, league)
        return self.league.get(lg, 0.0) + self.team.get(team_id, 0.0)

    def rally_prob(self, home_id, away_id, league: str, neutral=False) -> float:
        eta = (0 if neutral else self.home) + self.strength(home_id, league) - self.strength(away_id, league)
        return float(expit(eta))
