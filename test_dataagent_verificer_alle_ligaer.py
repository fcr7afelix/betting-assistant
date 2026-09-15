"""
Udvidelse af test_dataagent_verificer_navne.py til de fire resterende Big 5-
ligaer (Premier League er allerede verificeret 2026-09-01: 10/10 match efter
_normaliser_holdnavn()-rettelsen). Formaal: bekraefte eller afkraefte, at
holdnavne-normaliseringen ogsaa daekker Serie A, La Liga, Bundesliga og
Ligue 1 - IKKE en antagelse, indtil dette har koert.

Bruger RIGTIGE API-kald: 1 football-data.org-kald + 1 Odds API-kald PR.
liga (4 ligaer = 4 Odds API-kald, ét marked/én region hver). Cache er nu paa
plads (agents/cache.py) - en genkoersel af DETTE script inden for TTL'en
(15 min for odds, 1 time for kampe) genbruger de cachede svar og koster
INGEN yderligere credits.
"""
import sys

sys.path.insert(0, ".")

from agents.dataagent import hent_kampe, hent_odds, match_kamp_odds, DataagentFejl

MARKED = "Asian Handicap"  # Coolbet, markeds-noegle "spreads"
LIGAER = ["Serie A", "La Liga", "Bundesliga", "Ligue 1"]

samlet_matchede = 0
samlet_kampe = 0
ligaer_med_problemer = []

for liga in LIGAER:
    print(f"\n{'=' * 60}\n{liga}\n{'=' * 60}")
    try:
        kampe = hent_kampe(liga)
        odds_liste = hent_odds(liga, MARKED)
    except DataagentFejl as e:
        print(f"  DataagentFejl: {e}")
        ligaer_med_problemer.append((liga, f"API-fejl: {e}"))
        continue

    print(f"  {len(kampe)} kampe (football-data.org), {len(odds_liste)} kampe med odds (The Odds API)")

    kampe = match_kamp_odds(kampe, odds_liste)
    matchede = sum(1 for k in kampe if k["odds"] is not None)
    samlet_matchede += matchede
    samlet_kampe += len(kampe)

    print(f"  {matchede} / {len(kampe)} kampe matchede\n")
    for k in kampe:
        status = "MATCH" if k["odds"] is not None else "INGEN MATCH"
        print(f"    [{status}] {k['hjemmehold']!r} vs {k['udehold']!r}")

    if matchede < len(kampe):
        ligaer_med_problemer.append((liga, f"{len(kampe) - matchede} af {len(kampe)} kampe matchede IKKE"))
        # Vis raa Odds API-holdnavne til side-om-side sammenligning ved fejl
        print("\n  Raa holdnavne fra The Odds API (til sammenligning):")
        for o in odds_liste:
            print(f"    {o['hjemmehold']!r} / {o['udehold']!r}")

print(f"\n{'=' * 60}")
print(f"SAMLET: {samlet_matchede} / {samlet_kampe} kampe matchede paa tvaers af de 4 ligaer")
if ligaer_med_problemer:
    print("\nLIGAER MED PROBLEMER (kraever formentlig en udvidelse af _normaliser_holdnavn()):")
    for liga, besked in ligaer_med_problemer:
        print(f"  - {liga}: {besked}")
else:
    print("INGEN problemer - normaliseringen daekker alle 5 Big 5-ligaer (inkl. Premier League fra foer).")
