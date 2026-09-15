"""
Dataagenten: henter kampdata (football-data.org), odds (The Odds API) og
nyheder (Firecrawl.dev), og udvaelger ET match pr. session via Dataagentens
udvaelgelseskriterium: LAVESTE BOOKMAKER-MARGIN (se
claude/projekt-ramme-betting-agent.md for baggrunden - kriteriet hed
tidligere "udvaelgelses-EV", men blev omdoebt 2026-09-02 efter et
matematisk bevist degenerationsfund: for et 2-udfalds-marked er EV
beregnet paa bookmakerens EGNE normaliserede odds identisk for begge
udfald og afhaenger UDELUKKENDE af bookmakerens overround, ikke af hvilket
udfald der er bedst. Uden en uafhaengig sandsynlighedskilde kan denne
funktion aldrig detektere et "value bet" - den kan hoejst vaelge den kamp,
hvor bookmakeren tager mindst margin. Se "MATEMATISK DEGENERATIONSFUND" i
projektloggen for det fulde bevis).

Denne agent traeffer INGEN LLM-beslutning - al logik er deterministisk
Python, i traad med projektets kerneargument mod en CustomGPT-loesning.
"""
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from .cache import hent_med_cache

load_dotenv()

# TTL'er (sekunder) - kampe/nyheder aendrer sig langsomt, odds bevaeger sig
# hurtigere, men den bindende begraensning er The Odds API's 500 credits/md,
# saa 15 min er en bevidst afvejning mellem friskhed og kvoteforbrug under
# dev-iteration, IKKE et krav om realtids-noejagtighed for et eksamensprojekt.
KAMPE_TTL_SEKUNDER = 3600
ODDS_TTL_SEKUNDER = 900
NYHEDER_TTL_SEKUNDER = 3600
HISTORIK_TTL_SEKUNDER = 86400  # 24 timer - sidste saesons afsluttede kampe aendrer sig ikke


class DataagentFejl(Exception):
    """Rejses ved et fejlet API-kald (netvaerk, timeout, HTTP-fejl som 4xx/5xx)
    i en af Dataagentens hente-funktioner. Ét enkelt, klart fejllag: fanger
    requests' forskellige undtagelser og omsaetter dem til én dansksproget
    besked, som et UI-lag (fx app.py) kan vise direkte til brugeren - samme
    princip som try/except omkring client.messages.create() i app.py,
    fremfor at lade et raat requests-traceback naa brugeren."""

FOOTBALL_DATA_KEY = os.environ["FOOTBALL_DATA_KEY"]
ODDS_API_KEY = os.environ["ODDS_API_KEY"]
FIRECRAWL_API_KEY = os.environ["FIRECRAWL_API_KEY"]

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
FIRECRAWL_SEARCH_URL = "https://api.firecrawl.dev/v1/search"

# Ligamapping: dialog-promptens "liga"-felt (se AFKLARING_TOOL i
# orchestrator.py) -> football-data.org-kompetitionskode og The Odds API's
# sport_key. Begge bekraeftet empirisk i projektloggen 2026-08-29.
LIGA_TIL_FD_KODE = {
    "Premier League": "PL",
    "Ligue 1": "FL1",
    "Bundesliga": "BL1",
    "Serie A": "SA",
    "La Liga": "PD",
}
LIGA_TIL_ODDS_SPORT_KEY = {
    "Premier League": "soccer_epl",
    "Ligue 1": "soccer_france_ligue_one",
    "Bundesliga": "soccer_germany_bundesliga",
    "Serie A": "soccer_italy_serie_a",
    "La Liga": "soccer_spain_la_liga",
}

GYLDIGE_KAMP_STATUSSER = {"SCHEDULED", "TIMED"}
FALLBACK_BESKED = "Beklager, ingen kamp fra den liga er tilgængelig i denne periode."

# Marked -> bogmager. Over/Under 2.5 er fortsat laast til Unibet.
#
# Asian Handicap-bogmageren er LAAST OM TO GANGE (se projekt-ramme-
# betting-agent.md, "Asian Handicap - bogmager laast om" for fuld
# empirisk baggrund):
# 1) Oprindeligt (2026-09-01) laast til Coolbet.
# 2) 2026-09-14: Coolbet viste sig - verificeret ved et rigtigt API-kald
#    med "bookmakers=coolbet" direkte, IKKE bare regions=eu - at have
#    NUL markeder for ALLE kampe i alle fem ligaer paa dette tidspunkt.
#    Noeglen findes stadig (ingen fejl), men er reelt tom - en ekstern
#    afhaengighed der stille braekkede efter den oprindelige laasning,
#    uden nogen kodeaendring paa vores side. Erstattet med Pinnacle
#    (akademisk mest forsvarlige valg - branchens standard-reference
#    for skarpe, lav-margin-odds), verificeret empirisk 5/5-daekning
#    for Premier League, Ligue 1, Bundesliga og La Liga.
#
# PINNACLE HAR ET KENDT, DOKUMENTERET HUL: 0/13 kampe for Serie A paa
# maalingstidspunktet. Derfor en eksplicit, bevidst per-liga-undtagelse
# for Serie A: betonlineag (verificeret 12/13 daekning der), IKKE en ny
# universel standard - betonlineag daekker ikke alle fem ligaer lige
# godt og er et ureguleret offshore-bogmagerselskab, som Pinnacle bevidst
# blev foretrukket over hvor muligt (se Trin A/Trin B-beslutningen i
# hovedloggen for den fulde kritik af alle overvejede alternativer,
# inkl. hvorfor onexbet blev diskvalificeret paa omdoemme-grunde).
MARKED_TIL_BOGMAGER = {
    "Asian Handicap": "pinnacle",
    "Over/Under 2.5": "unibet_nl",
}
BOGMAGER_LIGA_UNDTAGELSER = {
    ("Asian Handicap", "Serie A"): "betonlineag",
}
MARKED_TIL_ODDS_NOEGLE = {
    "Asian Handicap": "spreads",
    "Over/Under 2.5": "totals",
}

# BUGFIX 2026-09-11 (fundet under empiri-log kamp 1, Man Utd - Man City):
# The Odds API's totals-marked kan indeholde FLERE linjer for samme
# kamp (fx BAADE 2.5 OG 3.5) som separate outcome-par i samme markeds-
# objekt. hent_odds() filtrerede IKKE paa point - alle outcomes blev
# samlet op uanset linje. Det ramte tre steder nedstroems: (1) de viste
# odds kunne vaere fra en helt anden linje end den valgte, (2) value
# signal sammenlignede historisk Over/Under-2.5-frekvens mod en
# implicit sandsynlighed fra en anden linje, (3) mest alvorligt: DET
# LAASTE udvaelgelseskriterium (_beregn_bookmaker_margin) summerede
# implicitte sandsynligheder paa tvaers af to forskellige markeder,
# hvilket goer selve margin-tallet - og dermed hvilken kamp der
# vaelges som kandidat 1 - meningsloest for enhver kamp med flere
# linjer tilgaengelige. KUN Over/Under 2.5 har en FAST linje at
# filtrere til; Asian Handicap's point er selve handicap-spaendet
# (varierer bevidst pr. hold) og skal IKKE filtreres paa samme maade.
MARKED_TIL_LINJE = {
    "Over/Under 2.5": 2.5,
}


def hent_kampe(liga, dage_frem=7):
    """Henter kommende kampe i den valgte liga fra football-data.org, inden
    for et rullende vindue paa `dage_frem` dage. Filtrerer til kun
    SCHEDULED/TIMED - andre statusser (POSTPONED, CANCELLED, SUSPENDED)
    frasorteres eksplicit, jf. LAAST krav i projektloggen. CACHET
    (KAMPE_TTL_SEKUNDER) for at spare paa football-data.org's 10 kald/min."""
    kode = LIGA_TIL_FD_KODE.get(liga)
    if kode is None:
        raise ValueError(f"Ukendt liga: {liga!r} - forventede en af {list(LIGA_TIL_FD_KODE)}")

    i_dag = datetime.now(timezone.utc).date()
    dato_til = i_dag + timedelta(days=dage_frem)
    cache_noegle = f"kampe:{kode}:{i_dag.isoformat()}:{dato_til.isoformat()}"

    def _rigtigt_kald():
        try:
            respons = requests.get(
                f"{FOOTBALL_DATA_BASE}/competitions/{kode}/matches",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params={"dateFrom": i_dag.isoformat(), "dateTo": dato_til.isoformat()},
                timeout=10,
            )
            respons.raise_for_status()
            data = respons.json()
        except requests.exceptions.RequestException as e:
            raise DataagentFejl(
                f"Kunne ikke hente kampdata for {liga} fra football-data.org: {e}"
            ) from e

        kampe = []
        for kamp in data.get("matches", []):
            if kamp.get("status") not in GYLDIGE_KAMP_STATUSSER:
                continue
            kampe.append({
                "hjemmehold": kamp["homeTeam"]["name"],
                "udehold": kamp["awayTeam"]["name"],
                "kickoff_utc": kamp["utcDate"],
            })
        return kampe

    return hent_med_cache(cache_noegle, KAMPE_TTL_SEKUNDER, _rigtigt_kald)


def hent_odds(liga, marked):
    """Henter odds for ALLE kampe i ligaen i ET enkelt kald (credit-forbrug =
    markeder x regioner, uafhaengigt af antal kampe - bekraeftet i
    projektloggen). Returnerer kun den bogmager, der er laast til det valgte
    marked. CACHET (ODDS_TTL_SEKUNDER) - den bindende kvote her er The Odds
    API's 500 credits/md, ikke et rate-limit, saa caching er saerligt
    vigtigt paa denne funktion under dev-iteration.

    Returnerer en LISTE af {"hjemmehold", "udehold", "outcomes"} - IKKE en
    dict med (hjemme, ude)-tuple-noegler, fordi tuple-noegler ikke er
    JSON-serialiserbare og derfor ikke kan caches direkte. match_kamp_odds()
    bygger selv et tuple-noeglet opslag af denne liste ved brug."""
    sport_key = LIGA_TIL_ODDS_SPORT_KEY.get(liga)
    if sport_key is None:
        raise ValueError(f"Ukendt liga: {liga!r}")

    odds_noegle = MARKED_TIL_ODDS_NOEGLE[marked]
    bogmager = BOGMAGER_LIGA_UNDTAGELSER.get((marked, liga), MARKED_TIL_BOGMAGER[marked])
    cache_noegle = f"odds:{sport_key}:{marked}"

    def _rigtigt_kald():
        try:
            respons = requests.get(
                f"{ODDS_API_BASE}/sports/{sport_key}/odds",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "eu",
                    "markets": odds_noegle,
                    "oddsFormat": "decimal",
                },
                timeout=10,
            )
            respons.raise_for_status()
            data = respons.json()
        except requests.exceptions.RequestException as e:
            raise DataagentFejl(
                f"Kunne ikke hente odds for {liga} ({marked}) fra The Odds API: {e}"
            ) from e

        linje = MARKED_TIL_LINJE.get(marked)
        odds_liste = []
        for begivenhed in data:
            for bm in begivenhed.get("bookmakers", []):
                if bm.get("key") != bogmager:
                    continue
                for m in bm.get("markets", []):
                    if m.get("key") != odds_noegle:
                        continue
                    outcomes = m.get("outcomes", [])
                    if linje is not None:
                        # Filtrer til DEN valgte linje - se BUGFIX-noten
                        # ved MARKED_TIL_LINJE ovenfor.
                        outcomes = [
                            o for o in outcomes
                            if o.get("point") is not None
                            and abs(o["point"] - linje) < 1e-9
                        ]
                    if not outcomes:
                        continue
                    odds_liste.append({
                        "hjemmehold": begivenhed["home_team"],
                        "udehold": begivenhed["away_team"],
                        "outcomes": outcomes,
                    })
        return odds_liste

    return hent_med_cache(cache_noegle, ODDS_TTL_SEKUNDER, _rigtigt_kald)


# Klub-affikser, der VERIFICERET (2026-09-01, rigtigt API-kald mod alle 10
# PL-kampe i vinduet) forekommer i football-data.org's holdnavne, men IKKE i
# The Odds API's - fx "Ipswich Town FC" vs "Ipswich Town", "AFC Bournemouth"
# vs "Bournemouth", "Sunderland AFC" vs "Sunderland". Uden normalisering
# matchede 0/10 rigtige kampe (bekraeftet empirisk, ikke en formodning).
_HOLDNAVN_AFFIKSER = {"fc", "afc", "cf"}


def _normaliser_holdnavn(navn):
    """Normaliserer et holdnavn til sammenligning paa tvaers af
    football-data.org og The Odds API: saenker til smaa bogstaver, erstatter
    "&" med "and" (fx "Brighton & Hove Albion" vs "Brighton and Hove
    Albion"), og fjerner isolerede klub-affiks-ord ("FC", "AFC", "CF") uanset
    om de staar foerst eller sidst i navnet. Daekker Premier League fuldt ud
    (10/10, verificeret empirisk), men IKKE de oevrige Big 5-ligaer alene -
    se HOLDNAVN_ALIASSER og _kanonisk_holdnavn() nedenfor."""
    navn = navn.strip().lower().replace("&", "and")
    ord = [o for o in navn.split() if o not in _HOLDNAVN_AFFIKSER]
    return " ".join(ord)


# Eksplicit alias-tabel: football-data.org's raa holdnavn (kun .strip().lower(),
# INGEN affiks-fjernelse) -> et kanonisk navn, der matcher The Odds API's
# navn efter samme normalisering. LAAST 2026-09-01, bygget UDELUKKENDE ud fra
# empiriske data (rigtige API-kald mod alle fem Big 5-ligaer samme dag) -
# INGEN opdigtede holdnavne. Bevidst valg (Trin A/Trin B i chatten): en
# regex-baseret loesning kan IKKE daekke rene kaldenavne (fx "Inter Milan"
# vs. "FC Internazionale Milano", "Lyon" vs. "Olympique Lyonnais") - kun en
# eksplicit tabel er deterministisk nok, i traad med projektets
# kerneargument om kodestyret kontrolflow frem for gaetteri.
#
# KENDT BEGRAENSNING: tabellen daekker KUN de klubber, der indgik i
# testvinduet 2026-09-01 (typisk 9-11 kampe pr. liga = ikke noedvendigvis
# alle 18-20 klubber i ligaen). En klub, der IKKE var med i test-vinduet
# (fx fordi den ikke spillede den uge), mangler en alias-indgang, indtil den
# observeres og tilfoejes. Vedligeholdelsesbyrde, IKKE en kodefejl - skal
# nævnes i Analyse/Perspektivering som en bevidst, dokumenteret begraensning
# af den manuelle tilgang.
HOLDNAVN_ALIASSER = {
    "Serie A": {
        "genoa cfc": "genoa",
        "como 1907": "como",
        "acf fiorentina": "fiorentina",
        "fc internazionale milano": "inter milan",
        "ssc napoli": "napoli",
        "parma calcio 1913": "parma",
        "ac monza": "monza",
        "frosinone calcio": "frosinone",
        "bologna fc 1909": "bologna",
        "us sassuolo calcio": "sassuolo",
        "cagliari calcio": "cagliari",
        "us lecce": "lecce",
        "udinese calcio": "udinese",
        "ss lazio": "lazio",
    },
    "La Liga": {
        "real sociedad de fútbol": "real sociedad",
        "rc celta de vigo": "celta vigo",
        "real betis balompié": "real betis",
        "club atlético de madrid": "atlético madrid",
        "athletic club": "athletic bilbao",
        "rayo vallecano de madrid": "rayo vallecano",
        "rc deportivo la coruña": "deportivo la coruña",
        "deportivo alavés": "alavés",
        "levante ud": "levante",
        "rcd espanyol de barcelona": "espanyol",
    },
    "Bundesliga": {
        "sv werder bremen": "werder bremen",
        "tsg 1899 hoffenheim": "tsg hoffenheim",
        "bayer 04 leverkusen": "bayer leverkusen",
        "1. fc union berlin": "union berlin",
        "sc paderborn 07": "sc paderborn",
        "sv 07 elversberg": "elversberg",
        "borussia mönchengladbach": "borussia monchengladbach",
        "fc bayern münchen": "bayern munich",
        "1. fsv mainz 05": "fsv mainz 05",
    },
    "Ligue 1": {
        "lille osc": "lille",
        "olympique lyonnais": "lyon",
        "aj auxerre": "auxerre",
        "paris saint-germain fc": "paris saint germain",
        "racing club de lens": "rc lens",
        "le havre ac": "le havre",
        "stade brestois 29": "brest",
        "ogc nice": "nice",
        "es troyes ac": "troyes",
        "rc strasbourg alsace": "strasbourg",
        "angers sco": "angers",
        "stade rennais fc 1901": "rennes",
        "olympique de marseille": "marseille",
    },
}


def _kanonisk_holdnavn(liga, navn):
    """Slaar op i HOLDNAVN_ALIASSER foerst (paa den RAA, kun sænket streng -
    ingen affiks-fjernelse); falder tilbage til den generelle
    _normaliser_holdnavn(), hvis intet alias findes (daekker Premier League
    fuldt ud, og enhver klub i andre ligaer, der IKKE har brug for et
    alias, fordi de to kilders navne allerede stemmer overens efter
    affiks-fjernelse alene, fx "AS Roma" i Serie A)."""
    raa_lav = navn.strip().lower()
    alias = HOLDNAVN_ALIASSER.get(liga, {}).get(raa_lav)
    if alias:
        return alias
    return _normaliser_holdnavn(navn)


def match_kamp_odds(liga, kampe, odds_liste):
    """Matcher football-data.org-kampe med The Odds API-odds paa KANONISKE
    holdnavne (ingen faelles ID mellem kilderne, jf. KENDT RISIKO i
    projektloggen) - se _kanonisk_holdnavn()/HOLDNAVN_ALIASSER ovenfor for
    hvorfor hverken ren streng-lighed (0/10 i Premier League-testen) eller
    ren affiks-normalisering (5/39 paa tvaers af de fire oevrige ligaer)
    var nok. `odds_liste` er formatet fra hent_odds(): en liste af
    {"hjemmehold", "udehold", "outcomes"} (JSON-cache-venligt format, se
    hent_odds()'s docstring). Kampe uden match faar odds=None og indgaar i
    fallback-logikken i vaelg_kamp()."""
    def noegle(hjemme, ude):
        return (_kanonisk_holdnavn(liga, hjemme), _kanonisk_holdnavn(liga, ude))

    odds_opslag = {
        noegle(o["hjemmehold"], o["udehold"]): o["outcomes"]
        for o in odds_liste
    }

    for kamp in kampe:
        kamp["odds"] = odds_opslag.get(noegle(kamp["hjemmehold"], kamp["udehold"]))
    return kampe


def _beregn_bookmaker_margin(outcomes):
    """Dataagentens udvaelgelseskriterium (OMDOEBT 2026-09-02, se
    projektloggens "MATEMATISK DEGENERATIONSFUND"): summerer bookmakerens
    implicitte sandsynligheder (1/odds) paa tvaers af markedets udfald.
    Summen er per konstruktion > 1 - overskuddet over 1 ER bookmakerens
    margin/vig (fx 0.05 = 5% margin). LAVERE margin = et relativt set
    "billigere" marked at spille paa, MEN dette er IKKE et maal for value
    eller for hvilket udfald der reelt vinder - det er udelukkende et
    maal for bookmakerens indbyggede fortjeneste paa markedet, uafhaengigt
    af hvilket udfald man vaelger. Den tidligere "udvaelgelses-EV" var
    matematisk identisk med denne margin-beregning for begge udfald i et
    2-udfalds-marked (bevist algebraisk: EV_i = 1/margin_sum - 1 for alle
    i) - dette navn er derfor blot en aerlig omdoebning af den samme
    beregning, ikke en ny/bedre metrik. Se ADVERSARIAL AUDIT i
    projektloggen for hvorfor selv margin-baseret udvaelgelse er en svag
    proxy for "bedste kamp"."""
    if not outcomes:
        return None

    implicitte_sandsynligheder = [1 / o["price"] for o in outcomes if o.get("price")]
    if not implicitte_sandsynligheder:
        return None

    samlet = sum(implicitte_sandsynligheder)
    if samlet <= 0:
        return None

    return samlet - 1


def _hent_matchede_kampe(liga, marked, dage_frem=7):
    """Henter kampe + odds og matcher dem, jf. vaelg_kamp()'s docstring -
    udtrukket 2026-09-09 saa vaelg_kamp() og rangér_kampe_med_odds() deler
    ÉT datagrundlag i stedet for at hente/matche hver sin gang. Returnerer
    en (muligvis tom) liste af kamp-dicts med et "bookmaker_margin"-felt
    tilfoejet (None hvis kampen ikke har odds)."""
    kampe = hent_kampe(liga, dage_frem=dage_frem)
    if not kampe:
        return []
    odds_pr_kamp = hent_odds(liga, marked)
    kampe = match_kamp_odds(liga, kampe, odds_pr_kamp)
    for kamp in kampe:
        kamp["bookmaker_margin"] = _beregn_bookmaker_margin(kamp["odds"]) if kamp["odds"] else None
    return kampe


def _rangér_med_margin(kampe):
    """Rangerer kandidater MED odds efter Dataagentens udvaelgelseskriterium
    (laveste bookmaker-margin foerst, tie-break naermeste kickoff) - udtrukket
    2026-09-09 saa vaelg_kamp() (tager kun toppen) og rangér_kampe_med_odds()
    (returnerer hele listen, til 'naeste kamp'-knappen i app.py) bruger PRAECIS
    samme rangering, ét sted. Kandidater UDEN odds indgaar ikke - de haandteres
    separat af vaelg_kamp()'s fallback 2 (naermeste kickoff, ingen rangering at
    tilbyde 'naeste kamp' fra i det tilfaelde)."""
    kandidater_med_margin = [k for k in kampe if k["bookmaker_margin"] is not None]
    return sorted(kandidater_med_margin, key=lambda k: (k["bookmaker_margin"], k["kickoff_utc"]))


def rangér_kampe_med_odds(liga, marked, dage_frem=7):
    """OFFENTLIG funktion til UI-laget (tilfoejet 2026-09-09 til 'naeste
    kamp'-knappen, se projektloggens opfoelgning). Samme datagrundlag og
    PRAECIS samme rangeringskriterium som vaelg_kamp() (LAAST, se dens
    docstring) - men returnerer HELE den rangerede kandidatliste (bedste
    foerst), ikke kun toppen. Tom liste hvis ingen kampe har odds; det er
    IKKE det samme som FALLBACK_BESKED (som er en brugervendt streng) -
    kaldere skal selv haandtere tom-liste-tilfaeldet (typisk ved at falde
    tilbage til vaelg_kamp()'s naermeste-kickoff-logik)."""
    kampe = _hent_matchede_kampe(liga, marked, dage_frem=dage_frem)
    return _rangér_med_margin(kampe)


def vaelg_kamp(liga, marked, dage_frem=7):
    """Orkestrerer hele udvaelgelsen: henter kampe + odds, matcher dem, og
    vaelger ET match efter Dataagentens udvaelgelseskriterium (OMDOEBT
    2026-09-02 fra "udvaelgelses-EV" til laveste bookmaker-margin, se
    projektloggens "MATEMATISK DEGENERATIONSFUND" for hvorfor - kriteriet
    er UAENDRET i beregning, kun aerligere navngivet):
    1. Blandt kandidater MED odds: vaelg LAVESTE bookmaker-margin.
       Tie-breaker: naermeste kickoff.
    2. Hvis INGEN kandidater har odds: fald tilbage til naermeste kickoff.
    3. Hvis der reelt ikke er nogen kampe: returner fallback-beskeden.
    Returnerer enten et kamp-dict (med et ekstra "bookmaker_margin"-felt,
    None ved fallback-tilfaelde 2) eller FALLBACK_BESKED (streng).

    RANGERINGSLOGIKKEN (trin 1) deles nu med rangér_kampe_med_odds() via
    _hent_matchede_kampe()/_rangér_med_margin() (udtrukket 2026-09-09) -
    denne funktions EGEN adfaerd er UAENDRET, kun den interne implementering
    er omlagt for at undgaa at rangeringskriteriet findes to steder."""
    kampe = _hent_matchede_kampe(liga, marked, dage_frem=dage_frem)
    if not kampe:
        return FALLBACK_BESKED

    kandidater = _rangér_med_margin(kampe)
    if kandidater:
        return kandidater[0]

    # Fallback 2: ingen kandidater har odds - naermeste kickoff
    return min(kampe, key=lambda k: k["kickoff_utc"])


def _sidste_saeson_for_kickoff(kickoff_utc_iso):
    """Udleder 'sidste saeson' (football-data.org's season-parameter er
    startaaret) ud fra en kamps kickoff-tidspunkt. Europaeiske saesoner
    starter i august - saa for en kickoff i januar-juli er DENNE saeson
    startet i det foregaaende kalenderaar, og SIDSTE saeson derfor to aar
    tilbage; for en kickoff i august-december er sidste saeson blot forrige
    kalenderaar."""
    fra_iso = kickoff_utc_iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(fra_iso)
    if dt.month >= 7:
        return dt.year - 1
    return dt.year - 2


def hent_team_id(liga, holdnavn):
    """Slaar et holds football-data.org-team-id op via ligaens holdliste
    (samme kildes navne som Dataagentens 'hjemmehold'/'udehold'-felter,
    saa opslaget er en direkte streng-noegle - INGEN kryds-kilde-
    normalisering noedvendig her, i modsaetning til match_kamp_odds()).
    Cachet med HISTORIK_TTL_SEKUNDER (holdlisten aendrer sig sjaeldent)."""
    kode = LIGA_TIL_FD_KODE.get(liga)
    if kode is None:
        raise ValueError(f"Ukendt liga: {liga!r}")
    cache_noegle = f"holdliste:{kode}"

    def _rigtigt_kald():
        try:
            respons = requests.get(
                f"{FOOTBALL_DATA_BASE}/competitions/{kode}/teams",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                timeout=10,
            )
            respons.raise_for_status()
            data = respons.json()
        except requests.exceptions.RequestException as e:
            raise DataagentFejl(f"Kunne ikke hente holdliste for {liga}: {e}") from e
        return {t["name"]: t["id"] for t in data.get("teams", [])}

    holdliste = hent_med_cache(cache_noegle, HISTORIK_TTL_SEKUNDER, _rigtigt_kald)
    return holdliste.get(holdnavn)


def hent_historisk_over_rate(team_id, sidste_saeson):
    """VALUE SIGNAL-datagrundlag (tilfoejet 2026-09-09, se projektloggens
    'Value signal - reversering af laast Transparensagent-design' for
    fuld begrundelse). Henter et holds op til 50 seneste AFSLUTTEDE kampe
    fra sidste saeson, PAA TVAERS AF ALLE TURNERINGER (bevidst valg -
    brugerens argument: et holds maalproduktion er tilstraekkeligt stabilt
    paa tvaers af turneringsniveau, fordi holdet ogsaa selv stiller
    svagere op mod svagere modstandere. Empirisk bekraeftet for Premier
    League vs. Champions League (55% vs. 47% Over-rate, 8pp forskel) -
    IKKE testet for laveste-niveau pokalkampe. Fortsat en accepteret,
    ikke fuldt verificeret antagelse - se Analyse).
    Cachet 24 timer (HISTORIK_TTL_SEKUNDER) - sidste saesons resultater
    aendrer sig ikke inden for projektperioden.

    TRANSPARENS-TILFOEJELSE (2026-09-09, opfoelgning paa oprykker-testen):
    fordi opslaget er team-scopet og ikke liga-scopet, henter det
    AUTOMATISK sidste-liga-data for et nyoprykket/nedrykket hold - fx
    Championship-kampe for et hold der nu spiller Premier League (empirisk
    bekraeftet 2026-09-09 for Coventry City, Hull City og Ipswich Town:
    46-49 Championship-kampe hver, ingen manglende data). Der er derfor
    INTET behov for et separat fallback - men det betyder ogsaa, at et
    value signal for et oprykket hold i praksis kan vaere baseret paa en
    anden liga end den, kampen faktisk spilles i. Det gjordes usynligt for
    brugeren; turnering_label loeser det ved at eksponere kildeturneringen.

    Returnerer (over_rate, antal_kampe, turnering_label). over_rate er
    None, hvis 0 kampe blev fundet. turnering_label er navnet paa
    turneringen kampene stammer fra, hvis de ALLE er fra samme turnering
    (fx 'Championship'); staar kampene fra flere turneringer, er det en
    kommasepareret streng af dem alle (fx 'Premier League, FA Cup'); er
    der 0 kampe, er det None."""
    cache_noegle = f"historik:{team_id}:{sidste_saeson}"

    def _rigtigt_kald():
        try:
            respons = requests.get(
                f"{FOOTBALL_DATA_BASE}/teams/{team_id}/matches",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
                params={"status": "FINISHED", "season": sidste_saeson, "limit": 50},
                timeout=10,
            )
            respons.raise_for_status()
            data = respons.json()
        except requests.exceptions.RequestException as e:
            raise DataagentFejl(f"Kunne ikke hente historik for hold {team_id}: {e}") from e

        over = 0
        total = 0
        turneringer = []  # bevarer raekkefoelge, dedupliceres ved visning
        for kamp in data.get("matches", []):
            score = kamp.get("score", {}).get("fullTime", {})
            hm, am = score.get("home"), score.get("away")
            if hm is None or am is None:
                continue
            total += 1
            if hm + am > 2.5:
                over += 1
            navn = kamp.get("competition", {}).get("name")
            if navn and navn not in turneringer:
                turneringer.append(navn)
        return {"over": over, "total": total, "turneringer": turneringer}

    resultat = hent_med_cache(cache_noegle, HISTORIK_TTL_SEKUNDER, _rigtigt_kald)
    if resultat["total"] == 0:
        return None, 0, None
    turnering_label = ", ".join(resultat.get("turneringer") or []) or None
    return resultat["over"] / resultat["total"], resultat["total"], turnering_label


def rens_tekst(tekst):
    """Deterministisk tekstoprensning (LAAST, gratis, intet ekstra
    API-kald): fjerner markdown-billeder, link-syntax og tabelraekker.
    Loeser stoej-problemet i Firecrawl-resultater, IKKE relevans-problemet
    (det er Analyseagentens ansvar, jf. projektloggen)."""
    if not tekst:
        return tekst
    tekst = re.sub(r"!\[.*?\]\(.*?\)", "", tekst)
    tekst = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", tekst)
    tekst = re.sub(r"^\|.*\|$", "", tekst, flags=re.MULTILINE)
    tekst = re.sub(r"\s{2,}", " ", tekst).strip()
    return tekst


def hent_nyheder(hjemmehold, udehold):
    """Henter nyheder/preview via Firecrawl.dev (`tbs: qdr:w`, IKKE
    kombineret med sbd:1 - jf. den laaste, dokumenterede Firecrawl-validering
    i projektloggen). Kildekvaliteten er BEVIDST IKKE filtreret her (hverken
    paa domaene eller relevans) - det er lagt til Analyseagent-niveau, som
    selv skal frasortere stoej og haandtere 0-relevante-resultater eksplicit.
    Returnerer en liste af {"titel", "url", "beskrivelse"}. CACHET
    (NYHEDER_TTL_SEKUNDER)."""
    forespoergsel = f"{hjemmehold} vs {udehold} preview news form injuries"
    cache_noegle = f"nyheder:{hjemmehold}:{udehold}"

    def _rigtigt_kald():
        try:
            respons = requests.post(
                FIRECRAWL_SEARCH_URL,
                headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
                json={"query": forespoergsel, "limit": 5, "tbs": "qdr:w"},
                timeout=20,
            )
            respons.raise_for_status()
            data = respons.json()
        except requests.exceptions.RequestException as e:
            raise DataagentFejl(
                f"Kunne ikke hente nyheder for {hjemmehold} vs {udehold} fra Firecrawl: {e}"
            ) from e

        resultater = []
        for r in data.get("data", []):
            resultater.append({
                "titel": r.get("title", ""),
                "url": r.get("url", ""),
                "beskrivelse": rens_tekst(r.get("description", "")),
            })
        return resultater

    return hent_med_cache(cache_noegle, NYHEDER_TTL_SEKUNDER, _rigtigt_kald)
