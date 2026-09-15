"""
Bekraeftelsestest (2026-09-09): kan football-data.org's GRATIS niveau
(TIER_ONE) levere et holds seneste N afsluttede kampe MED maaltal?
Dette er den eneste ubekraeftede forudsaetning for "Relative Value
Detection"-forslaget (v2) - hvis dette ikke virker, er forslaget dødt
kode uanset hvor "simpelt" beregningslaget er.

Koer i din egen terminal (IKKE via Cowork - se projektloggens
"Miljobegraensning: netvaerksadgang"):
  source venv/bin/activate
  python3 test_teamhistorik.py
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.environ["FOOTBALL_DATA_KEY"]
HEADERS = {"X-Auth-Token": KEY}
BASE = "https://api.football-data.org/v4"

print("1) Henter Premier League-holdliste (for at faa et rigtigt team-id)...")
r = requests.get(f"{BASE}/competitions/PL/teams", headers=HEADERS, timeout=15)
print("   STATUS:", r.status_code)
if r.status_code != 200:
    print("   FEJL:", r.text[:500])
    raise SystemExit("Kan ikke fortsaette - holdliste-kaldet fejlede.")

teams = r.json().get("teams", [])
print(f"   Fandt {len(teams)} hold.")
if not teams:
    raise SystemExit("Ingen hold i svaret.")

testhold = teams[0]
print(f"   Test-hold: {testhold['name']} (id={testhold['id']})")

time.sleep(6)  # TIER_ONE rate-limit: 10 kald/min - hold god margin

print("\n2) Henter holdets seneste 10 AFSLUTTEDE kampe med maaltal...")
url = f"{BASE}/teams/{testhold['id']}/matches"
params = {"status": "FINISHED", "limit": 10}
r2 = requests.get(url, headers=HEADERS, params=params, timeout=15)
print("   STATUS:", r2.status_code)
if r2.status_code != 200:
    print("   FEJL:", r2.text[:500])
    raise SystemExit("ENDEPUNKTET VIRKER IKKE PAA GRATIS NIVEAU (eller kraever anden query).")

data = r2.json()
kampe = data.get("matches", [])
print(f"   Fandt {len(kampe)} afsluttede kampe.")

if not kampe:
    raise SystemExit("Endepunktet svarer 200, men returnerer 0 kampe - tjek param-navne.")

print("\n3) Konkret uddata (det _byg_forslag()/v2-heuristikken faktisk skal bruge):")
over_count = 0
for k in kampe:
    hjemme = k["homeTeam"]["name"]
    ude = k["awayTeam"]["name"]
    score = k.get("score", {}).get("fullTime", {})
    hm, am = score.get("home"), score.get("away")
    dato = k.get("utcDate", "?")[:10]
    total_mal = (hm or 0) + (am or 0) if hm is not None and am is not None else None
    over = "OVER 2.5" if total_mal is not None and total_mal > 2.5 else ("UNDER 2.5" if total_mal is not None else "?")
    if over == "OVER 2.5":
        over_count += 1
    print(f"   {dato}  {hjemme} {hm}-{am} {ude}   ({over})")

print(f"\nKONKLUSION: {over_count}/{len(kampe)} af {testhold['name']}s seneste kampe gik Over 2.5.")
print("Hvis du ser rigtige kampe og score ovenfor: ENDEPUNKTET VIRKER PAA GRATIS NIVEAU.")
print("Rate-limit at holde oeje med: TIER_ONE er dokumenteret til 10 kald/min -")
print("to hold pr. kamp (hjemme+ude) betyder 2 kald pr. forslag oveni de eksisterende kald.")
