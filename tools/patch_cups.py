"""One-off patch: domestic cups via The Odds API, better club-name matching, no picks after kickoff."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sub(path, old, new):
    p = ROOT / path
    s = p.read_text(encoding="utf-8")
    assert s.count(old) == 1, f"{path}: {old[:70]!r} found {s.count(old)}x"
    p.write_text(s.replace(old, new), encoding="utf-8")


E = "src/europe.py"
sub(E, '''EURO = {  # our division code -> (The Odds API sport key, display name)
    "UCL": ("soccer_uefa_champs_league", "Champions League"),
    "UEL": ("soccer_uefa_europa_league", "Europa League"),
    "UECL": ("soccer_uefa_europa_conference_league", "Conference League"),
}''', '''# Every competition taken from The Odds API (European club competitions and the domestic cups
# of our leagues' countries): our division code -> (The Odds API sport key, display name).
# Cups out of season are checked for free and simply return no games.
EURO = {
    "UCL": ("soccer_uefa_champs_league", "Champions League"),
    "UEL": ("soccer_uefa_europa_league", "Europa League"),
    "UECL": ("soccer_uefa_europa_conference_league", "Conference League"),
    "EFLC": ("soccer_england_efl_cup", "EFL Cup"),
    "FAC": ("soccer_fa_cup", "FA Cup"),
    "DFBP": ("soccer_germany_dfb_pokal", "DFB-Pokal"),
    "CDR": ("soccer_spain_copa_del_rey", "Copa del Rey"),
    "CIT": ("soccer_italy_coppa_italia", "Coppa Italia"),
    "CDF": ("soccer_france_coupe_de_france", "Coupe de France"),
}
# where to look for a cup club's league name (European competitions search every league)
CUP_LEAGUES = {"EFLC": ["E0", "E1", "E2", "E3"], "FAC": ["E0", "E1", "E2", "E3"], "DFBP": ["D1"],
               "CDR": ["SP1"], "CIT": ["I1"], "CDF": ["F1"]}''')

sub(E, '''    "celtic": "Celtic", "rangers": "Rangers", "heart of midlothian": "Hearts", "aberdeen": "Aberdeen",
}''', '''    "celtic": "Celtic", "rangers": "Rangers", "heart of midlothian": "Hearts", "aberdeen": "Aberdeen",
    # English Football League
    "sheffield wednesday": "Sheffield Weds", "bristol rovers": "Bristol Rvs", "queens park rangers": "QPR",
    "west bromwich albion": "West Brom", "peterborough united": "Peterboro", "milton keynes dons": "Milton Keynes Dons",
    "mk dons": "Milton Keynes Dons", "afc wimbledon": "AFC Wimbledon", "wimbledon": "AFC Wimbledon",
    "preston north end": "Preston", "accrington stanley": "Accrington", "crawley town": "Crawley Town",
    "fleetwood town": "Fleetwood Town", "newport county": "Newport County", "notts county": "Notts County",
    "stockport county": "Stockport", "derby county": "Derby", "sutton united": "Sutton", "forest green rovers": "Forest Green",
    # Bundesliga
    "1 fc koln": "FC Koln", "fc koln": "FC Koln", "hamburger sv": "Hamburg", "fc st pauli": "St Pauli", "st pauli": "St Pauli",
    "1 fc heidenheim": "Heidenheim", "heidenheim": "Heidenheim", "fc augsburg": "Augsburg", "vfl bochum": "Bochum",
    "hertha berlin": "Hertha", "fortuna dusseldorf": "Fortuna Dusseldorf", "1 fc nurnberg": "Nurnberg",
    "sv darmstadt 98": "Darmstadt", "spvgg greuther furth": "Greuther Furth", "1 fc kaiserslautern": "Kaiserslautern",
    "arminia bielefeld": "Bielefeld", "eintracht braunschweig": "Braunschweig", "fc schalke 04": "Schalke 04",
    "holstein kiel": "Holstein Kiel", "sc paderborn 07": "Paderborn", "hannover 96": "Hannover",
    # La Liga
    "deportivo la coruna": "La Coruna", "real valladolid": "Valladolid", "rcd mallorca": "Mallorca",
    "ud las palmas": "Las Palmas", "real oviedo": "Oviedo", "cd leganes": "Leganes", "girona fc": "Girona",
    "sevilla fc": "Sevilla", "valencia cf": "Valencia", "villarreal cf": "Villarreal", "elche cf": "Elche",
    "levante ud": "Levante", "racing santander": "Santander", "sporting gijon": "Sp Gijon", "real zaragoza": "Zaragoza",
}''')

sub(E, '''def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9' -]", " ", s)
    s = re.sub(r"\\b(fc|afc|cf|sc|ac|sk|fk|jk|bk|if)\\b", " ", s)
    return re.sub(r"\\s+", " ", s).strip()


class TeamNames:
    """Map The Odds API club names onto football-data.co.uk names, so form and reasons use
    each club's league history. Clubs from other leagues keep their own name."""

    def __init__(self, hist: pd.DataFrame):
        self.known = sorted(set(hist["HomeTeam"]) | set(hist["AwayTeam"]))
        self.by_norm = {_norm(t): t for t in self.known}

    def __call__(self, name: str) -> str:
        raw = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
        if raw in ALIASES:
            return ALIASES[raw]
        n = _norm(name)
        if n in ALIASES:
            return ALIASES[n]
        if n in self.by_norm:
            return self.by_norm[n]
        close = difflib.get_close_matches(n, list(self.by_norm), n=1, cutoff=0.85)
        return self.by_norm[close[0]] if close else name''', '''def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9' -]", " ", s)
    s = re.sub(r"\\b(fc|afc|cf|sc|ac|sk|fk|jk|bk|if|1)\\b", " ", s)
    return re.sub(r"\\s+", " ", s).strip()


# words clubs often carry in one source but not the other ("Luton Town" vs "Luton")
_SUFFIX = r"\\b(city|town|united|utd|county|rovers|athletic|wanderers|albion|alexandra|stanley|hotspur)\\b"


def _short(name: str) -> str:
    return re.sub(r"\\s+", " ", re.sub(_SUFFIX, " ", _norm(name))).strip()


class TeamNames:
    """Map The Odds API club names onto football-data.co.uk names, so form and reasons use
    each club's league history. Clubs from other leagues keep their own name. `divs` limits
    the search to some leagues (a cup's own country)."""

    def __init__(self, hist: pd.DataFrame, divs: list[str] | None = None):
        h = hist[hist["Div"].isin(divs)] if divs else hist
        self.known = sorted(set(h["HomeTeam"]) | set(h["AwayTeam"]))
        self.by_norm = {_norm(t): t for t in self.known}
        shorts = {}
        for t in self.known:
            shorts.setdefault(_short(t), []).append(t)
        self.by_short = {k: v[0] for k, v in shorts.items() if len(v) == 1 and k}   # skip ambiguous ones

    def __call__(self, name: str) -> str:
        raw = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
        n = _norm(name)
        for k in (raw, n):
            if k in ALIASES and ALIASES[k] in self.known:
                return ALIASES[k]
        if n in self.by_norm:
            return self.by_norm[n]
        s = _short(name)
        if s in self.by_short:
            return self.by_short[s]
        close = difflib.get_close_matches(n, list(self.by_norm), n=1, cutoff=0.85)
        if close:
            return self.by_norm[close[0]]
        close = difflib.get_close_matches(s, list(self.by_short), n=1, cutoff=0.88)
        return self.by_short[close[0]] if close else name''')

sub(E, '''def europe_fixtures(today: pd.Timestamp, days: int, hist: pd.DataFrame, key: str) -> pd.DataFrame:
    """European games from today through the next `days` days, with prices. Spends credits
    only for competitions that have a game in the window."""
    names = TeamNames(hist)
    start, end = today, today + pd.Timedelta(days=days)
    frames = []
    for div, (sport, title) in EURO.items():
        events, _ = _get(f"{sport}/events", key)
        due = [e for e in events if start <= _uk_time(e["commence_time"]).tz_localize(None) < end]
        if not due:
            print(f"  {title}: no games in the window")
            continue
        odds, left = _get(f"{sport}/odds", key, regions="eu", markets="h2h,totals", oddsFormat="decimal",
                          commenceTimeFrom=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          commenceTimeTo=end.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _save_raw(f"{div}-odds", odds)
        fx = to_fixtures(odds, div, names)
        print(f"  {title}: {len(fx)} games priced ({left} credits left this month)")
        frames.append(fx)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()''',
    '''def europe_fixtures(today: pd.Timestamp, days: int, hist: pd.DataFrame, key: str) -> pd.DataFrame:
    """Games from today through the next `days` days in every competition above, with
    prices. Spends credits only for competitions that have a game still to kick off in the
    window; games already under way are left out."""
    now = pd.Timestamp.now(tz="UTC")
    start = max(pd.Timestamp(today).tz_localize("Europe/London").tz_convert("UTC"), now)
    end = (pd.Timestamp(today) + pd.Timedelta(days=days)).tz_localize("Europe/London").tz_convert("UTC")
    frames = []
    for div, (sport, title) in EURO.items():
        try:
            events, _ = _get(f"{sport}/events", key)
        except RuntimeError as e:   # e.g. a cup between seasons
            print(f"  {title}: no fixture list ({str(e)[:80]})")
            continue
        due = [e for e in events if start < pd.Timestamp(e["commence_time"]) < end]
        if not due:
            print(f"  {title}: no games still to play in the window")
            continue
        odds, left = _get(f"{sport}/odds", key, regions="eu", markets="h2h,totals", oddsFormat="decimal",
                          commenceTimeFrom=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          commenceTimeTo=end.strftime("%Y-%m-%dT%H:%M:%SZ"))
        _save_raw(f"{div}-odds", odds)
        odds = [e for e in odds if pd.Timestamp(e["commence_time"]) > now]
        fx = to_fixtures(odds, div, TeamNames(hist, CUP_LEAGUES.get(div)))
        print(f"  {title}: {len(fx)} games priced ({left} credits left this month)")
        frames.append(fx)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()''')

sub(E, '''        names = TeamNames(hist)
        for div in sorted(set(waiting["div"])):
            sport, title = EURO[div]
            scores, left = _get(f"{sport}/scores", key, daysFrom=3)''', '''        for div in sorted(set(waiting["div"])):
            sport, title = EURO[div]
            names = TeamNames(hist, CUP_LEAGUES.get(div))
            try:
                scores, left = _get(f"{sport}/scores", key, daysFrom=3)
            except RuntimeError as e:
                print(f"  {title}: scores unavailable ({str(e)[:80]})")
                continue''')
print("patched")
