"""
Validerer Firecrawl.dev's søgekvalitet på 2-3 RIGTIGE, kommende Big5-kampe.
Henter først kampene fra football-data.org (allerede bekræftet kilde), for
ikke at teste mod opdigtede/forældede kampnavne.
"""
import os
import re
import json
import datetime
import requests
from dotenv import load_dotenv


def rens_tekst(tekst):
    """Deterministisk oprensning af Firecrawl-beskrivelser - fjerner markdown-
    støj (billeder, tabelrækker, link-syntax), IKKE et Firecrawl-API-kald,
    ingen ekstra omkostning."""
    if not tekst:
        return tekst
    tekst = re.sub(r"!\[.*?\]\(.*?\)", "", tekst)          # billed-syntax
    tekst = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", tekst)  # link-syntax -> kun teksten
    tekst = re.sub(r"^\|.*\|$", "", tekst, flags=re.MULTILINE)  # tabelrækker
    tekst = re.sub(r"\n{2,}", "\n", tekst)
    tekst = re.sub(r"[ \t]{2,}", " ", tekst)
    return tekst.strip()

load_dotenv()

FD_KEY = os.environ["FOOTBALL_DATA_KEY"]
FC_KEY = os.environ["FIRECRAWL_API_KEY"]

# 1. Hent kommende Premier League-kampe i et 7-dages-vindue
i_dag = datetime.date.today()
om_en_uge = i_dag + datetime.timedelta(days=7)

fd_resp = requests.get(
    "https://api.football-data.org/v4/competitions/PL/matches",
    headers={"X-Auth-Token": FD_KEY},
    params={"dateFrom": str(i_dag), "dateTo": str(om_en_uge)},
    timeout=15,
)
fd_resp.raise_for_status()
kampe = [m for m in fd_resp.json()["matches"] if m["status"] in ("SCHEDULED", "TIMED")]

if not kampe:
    print("INGEN spilleklare Premier League-kampe fundet i vinduet - kan ikke teste videre.")
    raise SystemExit(1)

test_kampe = kampe[:3]
print(f"Fandt {len(kampe)} spilleklare kampe, tester Firecrawl på de første {len(test_kampe)}:\n")

for kamp in test_kampe:
    hjemme = kamp["homeTeam"]["name"]
    ude = kamp["awayTeam"]["name"]
    dato = kamp["utcDate"]
    forespoergsel = f"{hjemme} vs {ude} preview news form injuries"

    print(f"{'='*70}")
    print(f"KAMP: {hjemme} vs {ude} ({dato})")
    print(f"Firecrawl-forespørgsel: \"{forespoergsel}\"")
    print(f"{'='*70}")

    fc_resp = requests.post(
        "https://api.firecrawl.dev/v1/search",
        headers={
            "Authorization": f"Bearer {FC_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "query": forespoergsel,
            "limit": 5,
            "tbs": "qdr:w",  # KUN tidsbegrænsning (seneste uge) - IKKE dato-sortering ("sbd:1"),
            # da det viste sig at tilsidesætte relevans-rangeringen fuldstændigt (testet 2026-09-01)
        },
        timeout=30,
    )
    print(f"HTTP status: {fc_resp.status_code}")
    try:
        data = fc_resp.json()
        for resultat in data.get("data", []):
            print(f"- {resultat.get('title')}")
            print(f"  {resultat.get('url')}")
            print(f"  RENSET: {rens_tekst(resultat.get('description'))}")
            print()
    except Exception as e:
        print(f"Kunne ikke parse JSON: {e}")
        print(fc_resp.text[:1000])
    print()
