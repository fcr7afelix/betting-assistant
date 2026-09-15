"""
Test af oprykker-fallback (opfoelgning besluttet 2026-09-09).

Formaal: afgoere om football-data.org's team-scopede
/teams/{id}/matches?season=<sidste_saeson>-endpoint FAKTISK returnerer
kampe fra en anden turnering end den, holdet spiller i NU - fx
Championship-kampe for et hold der lige er rykket op i Premier League.

Hvis dette script finder 0 kampe for et kendt nyoprykket hold, er
konklusionen IKKE "koden virker ikke" - det er "API-nøglens tier
daekker ikke den turnering", og fallbacket kan ikke bygges uden en
anden datakilde.

KOER DETTE I DIN EGEN TERMINAL - Cowork/cloud-miljoeet har ikke
netvaerksadgang til football-data.org (bekraeftet flere gange).
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY") or os.environ.get("FOOTBALL_DATA_KEY")
BASE = "https://api.football-data.org/v4"

# RET DENNE LISTE til de faktiske nyoprykkede hold i den aktuelle PL-saeson
NYOPRYKKEDE_HOLD = ["Coventry City FC", "Hull City AFC", "Ipswich Town FC"]

def hent_pl_holdliste():
    r = requests.get(f"{BASE}/competitions/PL/teams", headers={"X-Auth-Token": API_KEY}, timeout=10)
    r.raise_for_status()
    return {t["name"]: t["id"] for t in r.json().get("teams", [])}

def hent_kampe(team_id, season):
    r = requests.get(
        f"{BASE}/teams/{team_id}/matches",
        headers={"X-Auth-Token": API_KEY},
        params={"status": "FINISHED", "season": season, "limit": 50},
        timeout=10,
    )
    print(f"  status={r.status_code}")
    r.raise_for_status()
    data = r.json()
    kampe = data.get("matches", [])
    turneringer = {}
    for k in kampe:
        navn = k.get("competition", {}).get("name", "?")
        turneringer[navn] = turneringer.get(navn, 0) + 1
    return len(kampe), turneringer

if __name__ == "__main__":
    print("Henter PL-holdliste...")
    holdliste = hent_pl_holdliste()

    for holdnavn in NYOPRYKKEDE_HOLD:
        team_id = holdliste.get(holdnavn)
        print(f"\n=== {holdnavn} (id={team_id}) ===")
        if team_id is None:
            print("  IKKE FUNDET i PL-holdliste - ret navnet i scriptet.")
            continue
        for season in (2025, 2024):
            print(f" sidste_saeson={season}:")
            antal, turneringer = hent_kampe(team_id, season)
            print(f"  {antal} kampe fundet. Turneringsfordeling: {turneringer}")

    print("\nKONKLUSION: se om nogen af de nyoprykkede hold har kampe fra")
    print("Championship/anden liga i turneringsfordelingen ovenfor. Hvis")
    print("ALLE viser 0 kampe eller kun 'Premier League'/'FA Cup' etc.,")
    print("daekker API-tieret formentlig ikke Championship, og fallbacket")
    print("kan ikke bygges uden en anden datakilde.")
