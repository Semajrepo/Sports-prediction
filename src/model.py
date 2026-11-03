"""Goals model: team attack/defence ratings blended with bookmaker-implied expected goals.

Every market (1X2, double chance, over/under, GG/NG, team goals, 1st half) is derived
from one pair of expected goals (lambda_home, lambda_away) through a Dixon-Coles
score matrix, so all picks for a match are mutually consistent.
"""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import poisson
from sklearn.linear_model import PoissonRegressor

MAX_GOALS = 10
RHO = -0.06           # Dixon-Coles low-score correction (draws slightly more likely than Poisson)
FIRST_HALF_SHARE = 0.44  # share of goals scored in the 1st half; re-estimated from data in backtest


# ---------------------------------------------------------------- score matrix

def score_matrix(lh: np.ndarray, la: np.ndarray, rho: float = RHO) -> np.ndarray:
    """Return (n, G, G) probabilities of each scoreline for n matches."""
    lh, la = np.atleast_1d(lh), np.atleast_1d(la)
    g = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(g[None, :], lh[:, None])
    pa = poisson.pmf(g[None, :], la[:, None])
    m = ph[:, :, None] * pa[:, None, :]
    # Dixon-Coles tau adjustment for 0-0, 1-0, 0-1, 1-1
    m[:, 0, 0] *= 1 - lh * la * rho
    m[:, 1, 0] *= 1 + la * rho
    m[:, 0, 1] *= 1 + lh * rho
    m[:, 1, 1] *= 1 - rho
    return m / m.sum(axis=(1, 2), keepdims=True)


def outcome_probs(m: np.ndarray) -> dict:
    """1X2 and total-goals summaries from score matrices."""
    g = np.arange(MAX_GOALS + 1)
    diff = g[:, None] - g[None, :]
    tot = g[:, None] + g[None, :]
    return {
        "H": (m * (diff > 0)).sum(axis=(1, 2)),
        "D": (m * (diff == 0)).sum(axis=(1, 2)),
        "A": (m * (diff < 0)).sum(axis=(1, 2)),
        "O25": (m * (tot > 2.5)).sum(axis=(1, 2)),
    }


# ---------------------------------------------------------------- market-implied lambdas

def devig(*odds):
    """Proportional de-vig: odds -> probabilities summing to 1."""
    inv = np.column_stack([1 / np.asarray(o, float) for o in odds])
    return inv / inv.sum(axis=1, keepdims=True)


class MarketInverter:
    """Find (lambda_home, lambda_away) whose 1X2 (+ O/U 2.5) probs best match the market.

    Uses a precomputed lambda grid and a KD-tree lookup, so it is fast for thousands of games.
    """

    def __init__(self, step=0.02, lo=0.15, hi=4.5):
        grid = np.arange(lo, hi, step)
        LH, LA = np.meshgrid(grid, grid, indexing="ij")
        self.lh, self.la = LH.ravel(), LA.ravel()
        p = {k: [] for k in ("H", "A", "O25")}
        for i in range(0, len(self.lh), 20000):
            o = outcome_probs(score_matrix(self.lh[i:i + 20000], self.la[i:i + 20000]))
            for k in p:
                p[k].append(o[k])
        p = {k: np.concatenate(v) for k, v in p.items()}
        self.tree_full = cKDTree(np.column_stack([p["H"], p["A"], p["O25"]]))
        self.tree_1x2 = cKDTree(np.column_stack([p["H"], p["A"]]))

    def invert(self, oh, od, oa, oo=None, ou=None):
        n = len(oh)
        out_h, out_a = np.full(n, np.nan), np.full(n, np.nan)
        p = devig(oh, od, oa)
        ok = np.isfinite(p).all(axis=1)
        has_ou = np.zeros(n, bool)
        if oo is not None:
            pou = devig(oo, ou)[:, 0]
            has_ou = ok & np.isfinite(pou)
            if has_ou.any():
                _, idx = self.tree_full.query(np.column_stack([p[has_ou, 0], p[has_ou, 2], pou[has_ou]]))
                out_h[has_ou], out_a[has_ou] = self.lh[idx], self.la[idx]
        only = ok & ~has_ou
        if only.any():
            _, idx = self.tree_1x2.query(np.column_stack([p[only, 0], p[only, 2]]))
            out_h[only], out_a[only] = self.lh[idx], self.la[idx]
        return out_h, out_a


# ---------------------------------------------------------------- team ratings

class TeamRatings:
    """Poisson regression: log(goals) = mu + attack[team] + defence[opponent] + home.

    Older matches are down-weighted with an exponential half-life. Teams with no history
    in the league (usually promoted sides) get the average rating of the weakest teams.
    """

    def __init__(self, half_life_days=200, alpha=0.002, window_days=3 * 365):
        self.half_life, self.alpha, self.window = half_life_days, alpha, window_days

    def fit(self, hist: pd.DataFrame, ref_date: pd.Timestamp):
        hist = hist[(hist["Date"] < ref_date) & (hist["Date"] >= ref_date - pd.Timedelta(days=self.window))]
        hist = hist.dropna(subset=["FTHG", "FTAG"])
        teams = sorted(set(hist["HomeTeam"]) | set(hist["AwayTeam"]))
        self.idx = {t: i for i, t in enumerate(teams)}
        n, k = len(hist), len(teams)
        if n < 50:
            self.ok = False
            return self
        hi = hist["HomeTeam"].map(self.idx).to_numpy()
        ai = hist["AwayTeam"].map(self.idx).to_numpy()
        X = np.zeros((2 * n, 2 * k + 1))
        r = np.arange(n)
        X[r, hi] = 1; X[r, k + ai] = 1; X[r, 2 * k] = 1        # home goals
        X[n + r, ai] = 1; X[n + r, k + hi] = 1                  # away goals
        y = np.concatenate([hist["FTHG"].to_numpy(), hist["FTAG"].to_numpy()])
        age = (ref_date - hist["Date"]).dt.days.to_numpy()
        w = np.tile(0.5 ** (age / self.half_life), 2)
        reg = PoissonRegressor(alpha=self.alpha, max_iter=300).fit(X, y, sample_weight=w)
        self.mu, self.k = reg.intercept_, k
        self.att, self.dfn, self.home = reg.coef_[:k], reg.coef_[k:2 * k], reg.coef_[2 * k]
        # prior for unseen teams: average of the weakest quarter
        strength = self.att - self.dfn
        weak = strength <= np.quantile(strength, 0.25)
        self.new_att, self.new_dfn = self.att[weak].mean(), self.dfn[weak].mean()
        self.ok = True
        return self

    def _ad(self, team):
        i = self.idx.get(team)
        return (self.new_att, self.new_dfn) if i is None else (self.att[i], self.dfn[i])

    def predict(self, home_teams, away_teams):
        if not self.ok:
            return np.full(len(home_teams), np.nan), np.full(len(home_teams), np.nan)
        H = np.array([self._ad(t) for t in home_teams])
        A = np.array([self._ad(t) for t in away_teams])
        lh = np.exp(self.mu + H[:, 0] + A[:, 1] + self.home)
        la = np.exp(self.mu + A[:, 0] + H[:, 1])
        return lh, la


def blend(lh_model, la_model, lh_mkt, la_mkt, w_market):
    """Geometric blend of model and market lambdas; falls back to whichever exists."""
    def mix(a, b):
        out = np.exp((1 - w_market) * np.log(a) + w_market * np.log(b))
        out = np.where(np.isnan(b), a, out)
        return np.where(np.isnan(a), b, out)
    return mix(lh_model, lh_mkt), mix(la_model, la_mkt)


# ---------------------------------------------------------------- corners & cards

def count_over_prob(mu, phi, line):
    """P(count > line) for counts with mean mu and variance phi * mu (both arrays allowed).

    phi > 1 -> negative binomial, phi < 1 -> binomial, phi ~ 1 -> Poisson.
    """
    from scipy.stats import binom, nbinom
    mu = np.asarray(mu, float)
    phi = np.broadcast_to(np.asarray(phi, float), mu.shape)
    k = np.floor(line)
    out = np.full(mu.shape, np.nan)
    over, under = phi > 1.02, phi < 0.98
    pois = ~over & ~under & np.isfinite(phi)
    if over.any():
        out[over] = nbinom.sf(k, mu[over] / (phi[over] - 1), 1 / phi[over])
    if under.any():
        n = np.maximum(np.round(mu[under] / (1 - phi[under])), np.ceil(mu[under]) + 1)
        out[under] = binom.sf(k, n, np.clip(mu[under] / n, 0, 1))
    if pois.any():
        out[pois] = poisson.sf(k, mu[pois])
    return np.where(np.isnan(mu), np.nan, out)


class CountRatings:
    """Per-team match counts (corners, cards):

    log E[count] = mu + for[team] + against[opponent] + home
                   + b1 * log(team's expected goals) + b2 * log(opponent's expected goals)
                   [+ referee]

    Expected goals come from bookmaker odds, so favourites/underdogs are handled even for
    teams with little history. Spread (phi = variance / mean) is estimated separately for
    one team's count and for the match total, because the two sides' counts are correlated.
    """

    def __init__(self, half_life_days=365, alpha=0.003, window_days=3 * 365, use_referee=False):
        self.half_life, self.alpha, self.window, self.use_referee = half_life_days, alpha, window_days, use_referee

    def fit(self, hist, ref_date, home_col, away_col):
        h = hist[(hist["Date"] < ref_date) & (hist["Date"] >= ref_date - pd.Timedelta(days=self.window))]
        h = h.dropna(subset=[home_col, away_col, "xg_h", "xg_a"])
        self.ok = len(h) >= 100
        if not self.ok:
            return self
        teams = sorted(set(h["HomeTeam"]) | set(h["AwayTeam"]))
        refs = sorted(h["Referee"].dropna().unique()) if self.use_referee and "Referee" in h else []
        self.tidx, self.ridx, k, nr = {t: i for i, t in enumerate(teams)}, {r: i for i, r in enumerate(refs)}, len(teams), len(refs)
        X = self._design(h["HomeTeam"], h["AwayTeam"], h["xg_h"], h["xg_a"], h.get("Referee"))
        y = np.concatenate([h[home_col].to_numpy(float), h[away_col].to_numpy(float)])
        age = (ref_date - h["Date"]).dt.days.to_numpy()
        w = np.tile(0.5 ** (age / self.half_life), 2)
        self.reg = PoissonRegressor(alpha=self.alpha, max_iter=500).fit(X, y, sample_weight=w)
        mu = self.reg.predict(X)
        n = len(h)
        self.phi_team = float(np.sum(w * (y - mu) ** 2) / np.sum(w * mu))
        yt, mt, wt = y[:n] + y[n:], mu[:n] + mu[n:], w[:n]
        self.phi_total = float(np.sum(wt * (yt - mt) ** 2) / np.sum(wt * mt))
        # league-average baseline (no team info), for measuring skill
        self.base_h, self.base_a = np.average(y[:n], weights=wt), np.average(y[n:], weights=wt)
        return self

    def _design(self, home, away, xg_h, xg_a, ref=None):
        k, nr, n = len(self.tidx), len(self.ridx), len(home)
        X = np.zeros((2 * n, 2 * k + 3 + nr))
        hi = np.array([self.tidx.get(t, -1) for t in home])
        ai = np.array([self.tidx.get(t, -1) for t in away])
        r = np.arange(n)
        for rows, own, opp in ((r, hi, ai), (n + r, ai, hi)):
            known = own >= 0
            X[rows[known], own[known]] = 1
            known = opp >= 0
            X[rows[known], k + opp[known]] = 1
        X[r, 2 * k] = 1
        lh, la = np.log(np.asarray(xg_h, float)), np.log(np.asarray(xg_a, float))
        X[r, 2 * k + 1], X[r, 2 * k + 2] = lh, la
        X[n + r, 2 * k + 1], X[n + r, 2 * k + 2] = la, lh
        if nr and ref is not None:
            ri = np.array([self.ridx.get(x, -1) for x in ref])
            for rows in (r, n + r):
                known = ri >= 0
                X[rows[known], 2 * k + 3 + ri[known]] = 1
        return X

    def predict(self, home, away, xg_h, xg_a, ref=None):
        n = len(home)
        if not self.ok:
            return np.full(n, np.nan), np.full(n, np.nan)
        mu = self.reg.predict(self._design(list(home), list(away), xg_h, xg_a, None if ref is None else list(ref)))
        return mu[:n], mu[n:]
