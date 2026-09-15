"""
Lille verifikationsscript til agents/dataagent.py - IKKE en del af
produktkoden. Formaal: afklare de to reelle, uverificerede antagelser fra
selvkritikken 2026-09-01:

1. Matcher football-data.org's og The Odds API's holdnavne-strenge
   eksakt (case-insensitivt)? (match_kamp_odds()-svagheden)
2. Hedder feltet i Odds API'ens outcomes-liste faktisk "price"?
   (_beregn_bookmaker_margin()-antagelsen)

Bruger RIGTIGE API-kald - koster ingen ekstra Firecrawl/Anthropic-credits,
men bruger 1 football-data.org-kald (10/min-graense) og 1 Odds API-kald
(traekker fra de 500 credits/md, markeder x regioner = formentlig 1-2
credits for ét marked, én region).
"""
import sys

sys.path.insert(0, ".")

from agents.dataagent import hent_kampe, hent_odds, match_kamp_odds

LIGA = "Premier League"
MARKED = "Asian Handicap"  # Coolbet, markeds-noegle "spreads"

print(f"=== Henter kampe: {LIGA} ===")
kampe = hent_kampe(LIGA)
print(f"{len(kampe)} kampe fundet (SCHEDULED/TIMED) i det rullende 7-dages-vindue:\n")
for k in kampe:
    print(f"  football-data.org: {k['hjemmehold']!r}  vs  {k['udehold']!r}   ({k['kickoff_utc']})")

print(f"\n=== Henter odds: {LIGA}, {MARKED} ===")
odds_pr_kamp = hent_odds(LIGA, MARKED)
print(f"{len(odds_pr_kamp)} kampe med odds fra Coolbet:\n")
for (hjemme, ude), outcomes in odds_pr_kamp.items():
    print(f"  The Odds API:      {hjemme!r}  vs  {ude!r}")
    if outcomes:
        print(f"    Første udfald (raa struktur): {outcomes[0]}")

print("\n=== Matcher kampene (match_kamp_odds) ===")
kampe = match_kamp_odds(kampe, odds_pr_kamp)
matchede = sum(1 for k in kampe if k["odds"] is not None)
print(f"{matchede} / {len(kampe)} kampe fik et odds-match.\n")
for k in kampe:
    status = "MATCH" if k["odds"] is not None else "INGEN MATCH"
    print(f"  [{status}] {k['hjemmehold']!r} vs {k['udehold']!r}")

if matchede < len(kampe):
    print(
        "\nADVARSEL: nogle kampe fik IKKE et odds-match. Sammenlign "
        "holdnavnene ovenfor manuelt - hvis et hold reelt findes i BEGGE "
        "lister, men med forskellige stavemåder/suffikser (fx 'FC', "
        "'Wanderers'), er det den formodede svaghed i match_kamp_odds(), "
        "der slår igennem."
    )

if odds_pr_kamp:
    _, eksempel_outcomes = next(iter(odds_pr_kamp.items()))
    if eksempel_outcomes and "price" not in eksempel_outcomes[0]:
        print(
            f"\nADVARSEL: feltet 'price' findes IKKE i outcome-strukturen - "
            f"faktiske nøgler: {list(eksempel_outcomes[0].keys())}. "
            f"_beregn_bookmaker_margin() skal rettes til at bruge det rigtige "
            f"feltnavn."
        )
    else:
        print("\nOK: feltet 'price' findes i outcome-strukturen som antaget.")
