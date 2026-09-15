"""
Fuld end-to-end-test af agents/dataagent.py: vaelg_kamp() (hele kaeden:
hent_kampe -> hent_odds -> match_kamp_odds -> bookmaker-margin-beregning) og
hent_nyheder() (Firecrawl). IKKE en del af produktkoden - scratch-fil.

Bevidst begraenset til Premier League for vaelg_kamp(): allerede den mest
verificerede liga (10/10 navnematch, bekraeftet to gange), saa denne test
fokuserer paa at bekraefte, at HELE KAEDEN haenger sammen (inkl. selve
EV-udregningen paa rigtige odds), ikke at gentteste navnematchningen for
de fire andre ligaer igen (allerede gjort, 76/76 offline-verificeret,
ingen grund til at bruge flere credits paa at gentage det).

Bruger RIGTIGE API-kald: football-data.org + Odds API for vaelg_kamp(),
Firecrawl for hent_nyheder(). Cachen (agents/cache.py) er fra i gaar og
dens TTL (max 1 time) er for laengst udloebet, saa alle kald rammer de
rigtige API'er igen.
"""
import sys

sys.path.insert(0, ".")

from agents.dataagent import vaelg_kamp, hent_nyheder, FALLBACK_BESKED, DataagentFejl

print("=== vaelg_kamp('Premier League', 'Asian Handicap') ===")
try:
    resultat = vaelg_kamp("Premier League", "Asian Handicap")
except DataagentFejl as e:
    print(f"DataagentFejl: {e}")
    resultat = None

if resultat == FALLBACK_BESKED:
    print(f"Fallback-besked returneret: {resultat!r}")
elif resultat is not None:
    print(f"Valgt kamp: {resultat['hjemmehold']} vs {resultat['udehold']}")
    print(f"Kickoff (UTC): {resultat['kickoff_utc']}")
    print(f"Dataagentens udvaelgelseskriterium (bookmaker-margin): {resultat['bookmaker_margin']}")
    print(f"Raa odds-udfald: {resultat['odds']}")

    if resultat["bookmaker_margin"] is None:
        print("\nADVARSEL: bookmaker_margin er None paa den VALGTE kamp - det betyder "
              "enten (a) ALLE kandidater manglede odds (fallback til naermeste "
              "kickoff blev brugt), eller (b) en fejl i margin-beregningen. Tjek "
              "'Raa odds-udfald' ovenfor manuelt.")
    else:
        print(f"\nOK: en gyldig kamp med en beregnet bookmaker-margin blev valgt.")

    print(f"\n=== hent_nyheder('{resultat['hjemmehold']}', '{resultat['udehold']}') ===")
    try:
        nyheder = hent_nyheder(resultat["hjemmehold"], resultat["udehold"])
        print(f"{len(nyheder)} resultater fundet:\n")
        for n in nyheder:
            print(f"  - {n['titel']}")
            print(f"    {n['url']}")
            print(f"    {n['beskrivelse'][:200]}{'...' if len(n['beskrivelse']) > 200 else ''}\n")
        if not nyheder:
            print("  0 resultater - jf. den kendte, dokumenterede Firecrawl-inkonsistens "
                  "(se projektloggen). IKKE noedvendigvis en fejl i koden.")
    except DataagentFejl as e:
        print(f"DataagentFejl: {e}")
