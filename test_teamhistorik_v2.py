"""
Udvidet bekraeftelsestest (2026-09-09): kan vi supplere den tynde
in-season-historik (n=3, se forrige test) med sidste saesons kampe og/eller
pokalkampe, uden at ramme betalingsspaerre eller for skaev en fordeling?

Koer i din egen terminal:
  source venv/bin/activate
  python3 test_teamhistorik_v2.py
"""
import os
import time
import requests
from dotenv import load_dotenv
from collections import Counter

load_dotenv()
KEY = os.environ["FOOTBALL_DATA_KEY"]
HEADERS = {"X-Auth-Token": KEY}
BASE = "https://api.football-data.org/v4"

TEAM_ID = 57  # Arsenal FC, samme testhold som sidst - genbrug for sammenlignelighed
DENNE_SAESON = 2026
SIDSTE_SAESON = 2025

def hent_kampe(team_id, season, label):
    print(f"\n--- {label} (season={season}) ---")
    url = f"{BASE}/teams/{team_id}/matches"
    params = {"status": "FINISHED", "season": season, "limit": 50}
    r = requests.get(url, headers=HEADERS, params=params, timeout=15)
    print("STATUS:", r.status_code)
    if r.status_code == 403:
        print("SPAERRET: dette er en betalt-plan-begraensning, samme moenster som Odds-historik.")
        return []
    if r.status_code != 200:
        print("FEJL:", r.text[:300])
        return []
    kampe = r.json().get("matches", [])
    print(f"Fandt {len(kampe)} afsluttede kampe.")
    return kampe

print("1) Denne saesons kampe (samme som forrige test, til reference)...")
denne = hent_kampe(TEAM_ID, DENNE_SAESON, "Denne saeson")
time.sleep(6)

print("\n2) Sidste saesons kampe...")
sidste = hent_kampe(TEAM_ID, SIDSTE_SAESON, "Sidste saeson")

alle = denne + sidste
if not alle:
    raise SystemExit("Ingen kampe fundet overhovedet - kan ikke fortsaette analysen.")

print(f"\n3) Turneringsfordeling blandt alle {len(alle)} fundne kampe:")
turneringer = Counter(k.get("competition", {}).get("name", "?") for k in alle)
for navn, antal in turneringer.most_common():
    print(f"   {navn}: {antal}")

print("\n4) Over/Under 2.5-fordeling, opdelt paa turnering:")
per_turnering = {}
for k in alle:
    navn = k.get("competition", {}).get("name", "?")
    score = k.get("score", {}).get("fullTime", {})
    hm, am = score.get("home"), score.get("away")
    if hm is None or am is None:
        continue
    total = hm + am
    per_turnering.setdefault(navn, []).append(total > 2.5)

for navn, resultater in per_turnering.items():
    if resultater:
        rate = sum(resultater) / len(resultater)
        print(f"   {navn}: {sum(resultater)}/{len(resultater)} Over 2.5 ({rate*100:.0f}%)")

print("\nKONKLUSION: sammenlign turneringernes individuelle Over-rate ovenfor.")
print("Hvis de ligger taet paa hinanden, er poolingen rimelig. Hvis de spreder sig")
print("meget (fx pokalkampe markant hoejere/lavere end liga), bekraefter det")
print("comparability-bekymringen og kraever eksplicit vaegtning/udelukkelse.")
