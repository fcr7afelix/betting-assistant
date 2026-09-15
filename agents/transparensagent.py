"""
Transparensagenten (OMDOEBT 2026-09-08 fra "Vaerdi/Risikoagent", se
projektloggen: "Agent-omdoebning"): omsaetter Dataagentens bookmaker_margin
og Analyseagentens kontekst til et risikobillede - UDEN at foretage nogen ny
beregning, og UDEN at afgive en vaerdipaastand.

100% DETERMINISTISK - INGEN LLM-kald i denne fil. Det er hele pointen: efter
det matematiske degenerationsfund 2026-09-02 (se projektloggen) ved vi, at
enhver ny "EV"/"vaerdi"-beregning paa bookmakerens egne odds er cirkulaer
uden en uafhaengig sandsynlighedskilde, som projektet bevidst har fravalgt
at bygge (egen model, Pinnacle, reference-games og cross-liga-soegning er
alle afvist, se separate sektioner i projektloggen). Transparensagenten
loeser IKKE det problem - den skjuler det ikke heller. Den viderestiller kun
data, den allerede har faaet, og tilfoejer en fast, aerlig disclaimer.
"""

FAST_DISCLAIMER = (
    "Systemets bidrag: gennemsigtig markedsdata + kontekst. "
    "INGEN uafhængig sandsynlighedsvurdering."
)


def _formater_udfald_navn(outcome):
    """Bygger et laesbart navn til ét odds-udfald fra The Odds API's raa
    format ({"name", "price", evt. "point"}). For Asian Handicap/Over-Under
    inkluderer "point" selve linjen (fx handicap eller total) - uden den er
    navnet vildledende (fx blot "Over" uden at vise "2.5"). Ren
    tekstformatering, ingen fortolkning af, hvad der er "bedst"."""
    navn = outcome.get("name", "?")
    point = outcome.get("point")
    if point is not None:
        return f"{navn} {point}"
    return navn


def byg_risikobillede(kamp, kontekst):
    """Bygger risikobilledet til Vurderingsagentens bet assessment-kort.

    kamp: et kamp-dict fra Dataagentens vaelg_kamp() (skal have "hjemmehold",
      "udehold", "kickoff_utc", "odds" og "bookmaker_margin").
    kontekst: Analyseagentens output-dict fra analyser_nyheder() (viderestillet
      UAENDRET - ingen ny fortolkning her).

    BEVIDST DESIGNVALG (flagges eksplicit, ikke stiltiende antaget): der
    findes INTET grundlag i arkitekturen for at pege paa ét udfald som "det
    anbefalede vaeddemaal" - det ville kraeve netop den uafhaengige
    sandsynlighedsvurdering, som er fravalgt. Derfor viser risikobilledet
    BEGGE/ALLE udfald i markedet sideordnet, sorteret efter laveste odds
    foerst (den odds-mæssige favorit) - en ren visningskonvention, IKKE en
    anbefaling. Se projektloggen "Bet Assessment-kort" for hvorfor dette
    afviger fra det oprindelige, brugerforeslaaede eksempel (som viste ét
    udvalgt udfald).

    Returnerer et dict med samme facon hver gang - ingen af felterne
    beregnes paa ny, kun formateret/viderestillet.
    """
    outcomes = kamp.get("odds") or []
    udfald = []
    for o in sorted(outcomes, key=lambda x: x.get("price", float("inf"))):
        price = o.get("price")
        udfald.append({
            "navn": _formater_udfald_navn(o),
            "odds": price,
            "implicit_sandsynlighed": (1 / price) if price else None,
        })

    return {
        "hjemmehold": kamp.get("hjemmehold"),
        "udehold": kamp.get("udehold"),
        "kickoff_utc": kamp.get("kickoff_utc"),
        "udfald": udfald,
        "bookmaker_margin": kamp.get("bookmaker_margin"),
        "kontekst": kontekst,
        "disclaimer": FAST_DISCLAIMER,
    }
