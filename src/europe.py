"""Champions League, Europa League and Conference League from The Odds API.

football-data.co.uk has no European club competitions, so their fixtures, bookmaker
prices and results come from The Odds API (free plan: 500 credits a month). Credits are
spent only when needed:

  /events   fixture list                         free, checked every run
  /odds     1X2 + Over/Under, one region (eu)    about 2 credits per competition, only when
                                                 it has a game in the prediction window
  /scores   final scores of the last 3 days      2 credits per competition, only when a
                                                 European pick is waiting for its result

Result and goals picks work exactly as for the leagues, since they come from bookmaker
prices. Corners and cards need each club's league history, so there are none for European
games yet. 1st-half picks are skipped because the free scores have no half-time result.

The key is read from the ODDS_API_KEY environment variable or config/odds_api_key.txt.
"""
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "config" / "odds_api_key.txt"
EURO_DIR = ROOT / "data" / "europe"
RESULTS = EURO_DIR / "results.csv"
API = "https://api.the-odds-api.com/v4/sports"

# Every competition taken from The Odds API (European club competitions and the domestic cups
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
               "CDR": ["SP1"], "CIT": ["I1"], "CDF": ["F1"]}
EURO_NAMES = {div: name for div, (_, name) in EURO.items()}
# Our leagues on The Odds API: used only when football-data.co.uk hasn't listed a league's
# games in the window yet (it often publishes weekend fixtures late)
LEAGUE_ODDS = {
    "E0": "soccer_epl", "E1": "soccer_efl_champ", "E2": "soccer_england_league1", "E3": "soccer_england_league2",
    "SP1": "soccer_spain_la_liga", "I1": "soccer_italy_serie_a", "D1": "soccer_germany_bundesliga",
    "F1": "soccer_france_ligue_one", "N1": "soccer_netherlands_eredivisie", "P1": "soccer_portugal_primeira_liga",
    "B1": "soccer_belgium_first_div", "T1": "soccer_turkey_super_league", "G1": "soccer_greece_super_league",
    "SC0": "soccer_spl",
}

# The Odds API name -> football-data.co.uk name, where simple matching can't tell
ALIASES = {
    "manchester city": "Man City", "manchester united": "Man United", "tottenham hotspur": "Tottenham",
    "newcastle united": "Newcastle", "nottingham forest": "Nott'm Forest", "wolverhampton wanderers": "Wolves",
    "brighton and hove albion": "Brighton", "west ham united": "West Ham", "aston villa": "Aston Villa",
    "atletico madrid": "Ath Madrid", "athletic bilbao": "Ath Bilbao", "athletic club": "Ath Bilbao",
    "real betis": "Betis", "real sociedad": "Sociedad", "celta vigo": "Celta", "rayo vallecano": "Vallecano",
    "espanyol": "Espanol", "deportivo alaves": "Alaves",
    "inter milan": "Inter", "internazionale": "Inter", "ac milan": "Milan", "as roma": "Roma", "ss lazio": "Lazio",
    "ssc napoli": "Napoli", "atalanta bc": "Atalanta", "acf fiorentina": "Fiorentina",
    "bayern munich": "Bayern Munich", "fc bayern munchen": "Bayern Munich", "borussia dortmund": "Dortmund",
    "bayer leverkusen": "Leverkusen", "rb leipzig": "RB Leipzig", "eintracht frankfurt": "Ein Frankfurt",
    "vfb stuttgart": "Stuttgart", "borussia monchengladbach": "M'gladbach", "sc freiburg": "Freiburg",
    "tsg hoffenheim": "Hoffenheim", "vfl wolfsburg": "Wolfsburg", "1 fc union berlin": "Union Berlin",
    "fsv mainz 05": "Mainz", "werder bremen": "Werder Bremen",
    "paris saint germain": "Paris SG", "paris saint-germain": "Paris SG", "olympique marseille": "Marseille",
    "olympique lyonnais": "Lyon", "as monaco": "Monaco", "stade rennais": "Rennes", "losc lille": "Lille",
    "ogc nice": "Nice", "rc lens": "Lens", "stade brestois 29": "Brest", "rc strasbourg": "Strasbourg",
    "fc twente enschede": "Twente", "twente enschede": "Twente", "nec nijmegen": "Nijmegen",
    "psv eindhoven": "PSV Eindhoven", "ajax amsterdam": "Ajax", "az alkmaar": "AZ Alkmaar", "feyenoord rotterdam": "Feyenoord",
    "fc twente": "Twente", "fc utrecht": "Utrecht", "go ahead eagles": "Go Ahead Eagles",
    "sporting lisbon": "Sp Lisbon", "sporting cp": "Sp Lisbon", "fc porto": "Porto", "sl benfica": "Benfica",
    "sc braga": "Sp Braga", "vitoria guimaraes": "Guimaraes",
    "club brugge": "Club Brugge", "royal antwerp": "Antwerp", "rsc anderlecht": "Anderlecht", "krc genk": "Genk",
    "union saint-gilloise": "St. Gilloise", "royale union saint-gilloise": "St. Gilloise", "kaa gent": "Gent",
    "standard liege": "Standard", "plymouth argyle": "Plymouth", "panetolikos agrinio": "Panetolikos",
    "ae kifisia fc": "Kifisia", "fortuna sittard": "For Sittard", "ado den haag": "Den Haag", "cs maritimo": "Maritimo",
    "braga": "Sp Braga", "falkirk f.c.": "Falkirk", "basaksehir": "Buyuksehyr", "gazisehir gaziantep": "Gaziantep",
    "caykur rizespor": "Rizespor", "torku konyaspor": "Konyaspor", "real racing club de santander": "Santander",
    "galatasaray sk": "Galatasaray", "fenerbahce sk": "Fenerbahce", "besiktas jk": "Besiktas", "trabzonspor": "Trabzonspor",
    "olympiacos piraeus": "Olympiakos", "olympiakos piraeus": "Olympiakos", "olympiacos": "Olympiakos", "paok thessaloniki": "PAOK", "aek athens": "AEK",
    "panathinaikos": "Panathinaikos",
    "celtic": "Celtic", "rangers": "Rangers", "heart of midlothian": "Hearts", "aberdeen": "Aberdeen",
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
}


def ninety_minute_score(div: str, date) -> bool:
    """Is The Odds API's final score the 90-minute score? Picks are settled on 90 minutes only.

    European league-phase games (September to January) can't go to extra time, so yes. Cup
    games and European knockout games can go to extra time or penalties, and the API doesn't
    say which, so their picks wait for a source that reports the 90-minute score.
    """
    return div in ("UCL", "UEL", "UECL") and pd.Timestamp(date).month in (9, 10, 11, 12, 1)


def api_key() -> str | None:
    if os.environ.get("ODDS_API_KEY"):
        return os.environ["ODDS_API_KEY"].strip()
    if KEY_FILE.exists():
        for line in KEY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and line != "PASTE_KEY_HERE":
                return line
    return None


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9' -]", " ", s)
    s = re.sub(r"\b(fc|afc|cf|sc|ac|sk|fk|jk|bk|if|1|sd|cd|ud|rcd|sv|vfl|vfb|tsg|fsv|ssv|spvgg|tsv|ssc|ss|as|rc|ogc|losc|kaa|krc|rsc|sl)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# words clubs often carry in one source but not the other ("Luton Town" vs "Luton")
_SUFFIX = r"\b(city|town|united|utd|county|rovers|athletic|wanderers|albion|alexandra|stanley|hotspur)\b"


def _short(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(_SUFFIX, " ", _norm(name))).strip()


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
        return self.by_short[close[0]] if close else name


def _get(path: str, key: str, **params):
    r = requests.get(f"{API}/{path}", params={"apiKey": key, **params}, timeout=30)
    left = r.headers.get("x-requests-remaining")
    if r.status_code != 200:
        raise RuntimeError(f"The Odds API {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json(), left


def _save_raw(name: str, data):
    (EURO_DIR / "raw").mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d-%H%M%S")
    (EURO_DIR / "raw" / f"{stamp}-{name}.json").write_text(json.dumps(data), encoding="utf-8")


def _uk_time(iso: str) -> pd.Timestamp:
    return pd.Timestamp(iso).tz_convert("Europe/London")


def to_fixtures(events: list[dict], div: str, names: TeamNames) -> pd.DataFrame:
    """Odds API events (with bookmakers) -> rows shaped like football-data.co.uk's fixtures.csv."""
    rows = []
    for e in events:
        h2h = {"H": [], "D": [], "A": []}
        tot = {"O": [], "U": []}
        for b in e.get("bookmakers", []):
            for mk in b.get("markets", []):
                if mk["key"] == "h2h":
                    for o in mk["outcomes"]:
                        side = "H" if o["name"] == e["home_team"] else "A" if o["name"] == e["away_team"] else "D"
                        h2h[side].append(float(o["price"]))
                elif mk["key"] == "totals":
                    for o in mk["outcomes"]:
                        if abs(float(o.get("point", 0)) - 2.5) < 1e-9:
                            tot["O" if o["name"].lower() == "over" else "U"].append(float(o["price"]))
        if not all(h2h.values()):
            continue   # no complete 1X2 prices: no picks for this game
        t = _uk_time(e["commence_time"])
        row = {"Div": div, "Date": t.tz_localize(None).normalize(), "Time": t.strftime("%H:%M"),
               "HomeTeam": names(e["home_team"]), "AwayTeam": names(e["away_team"]),
               "Referee": np.nan, "event_id": e["id"], "books": len(e.get("bookmakers", []))}
        for s, col in (("H", "H"), ("D", "D"), ("A", "A")):
            row[f"Avg{col}"], row[f"Max{col}"] = float(np.mean(h2h[s])), float(np.max(h2h[s]))
        for s, col in (("O", ">2.5"), ("U", "<2.5")):
            row[f"Avg{col}"] = float(np.mean(tot[s])) if tot[s] else np.nan
            row[f"Max{col}"] = float(np.max(tot[s])) if tot[s] else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def europe_fixtures(today: pd.Timestamp, days: int, hist: pd.DataFrame, key: str, comps: dict | None = None) -> pd.DataFrame:
    """Games from today through the next `days` days in every competition above, with
    prices. Spends credits only for competitions that have a game still to kick off in the
    window; games already under way are left out."""
    now = pd.Timestamp.now(tz="UTC")
    start = max(pd.Timestamp(today).tz_localize("Europe/London").tz_convert("UTC"), now)
    end = (pd.Timestamp(today) + pd.Timedelta(days=days)).tz_localize("Europe/London").tz_convert("UTC")
    frames = []
    for div, (sport, title) in (comps or EURO).items():
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
        fx = to_fixtures(odds, div, TeamNames(hist, [div] if div in LEAGUE_ODDS else CUP_LEAGUES.get(div)))
        print(f"  {title}: {len(fx)} games priced ({left} credits left this month)")
        frames.append(fx)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def update_results(log: pd.DataFrame, today: pd.Timestamp, hist: pd.DataFrame, key: str) -> pd.DataFrame:
    """Fetch final scores for European picks still waiting for a result (last 3 days only,
    which is all the API keeps), add them to data/europe/results.csv and return every stored result."""
    stored = pd.read_csv(RESULTS) if RESULTS.exists() else pd.DataFrame(columns=["Div", "Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    if not log.empty and "div" in log:
        cutoff = (today - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
        waiting = log[log["div"].isin(EURO) & (log["result"] == "") & (log["date"] < today.strftime("%Y-%m-%d"))
                      & (log["date"] >= cutoff)]
        waiting = waiting[[ninety_minute_score(d, t) for d, t in zip(waiting["div"], waiting["date"])]]   # no credits for cups
        for div in sorted(set(waiting["div"])):
            sport, title = EURO[div]
            names = TeamNames(hist, CUP_LEAGUES.get(div))
            try:
                scores, left = _get(f"{sport}/scores", key, daysFrom=3)
            except RuntimeError as e:
                print(f"  {title}: scores unavailable ({str(e)[:80]})")
                continue
            _save_raw(f"{div}-scores", scores)
            new = []
            for e in scores:
                if not e.get("completed") or not e.get("scores"):
                    continue
                s = {x["name"]: x["score"] for x in e["scores"]}
                new.append({"Div": div, "Date": _uk_time(e["commence_time"]).strftime("%Y-%m-%d"),
                            "HomeTeam": names(e["home_team"]), "AwayTeam": names(e["away_team"]),
                            "FTHG": int(s[e["home_team"]]), "FTAG": int(s[e["away_team"]])})
            print(f"  {title}: {len(new)} final scores ({left} credits left this month)")
            stored = pd.concat([stored, pd.DataFrame(new)], ignore_index=True)
        stored = stored.drop_duplicates(["Div", "Date", "HomeTeam", "AwayTeam"], keep="last")
        stored = stored[[ninety_minute_score(d, t) for d, t in zip(stored["Div"], stored["Date"])]]
        EURO_DIR.mkdir(parents=True, exist_ok=True)
        stored.to_csv(RESULTS, index=False)
    return stored
