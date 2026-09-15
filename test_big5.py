import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
key = os.environ.get("ODDS_API_KEY")

leagues = [
    "soccer_france_ligue_one",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_spain_la_liga",
]

for liga in leagues:
    resp = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{liga}/odds",
        params={
            "apiKey": key,
            "regions": "eu",
            "markets": "spreads,totals,h2h",
            "oddsFormat": "decimal",
        },
    )
    print(f"\n=== {liga} — status {resp.status_code} ===")
    data = resp.json()
    if not isinstance(data, list) or len(data) == 0:
        print("Ingen kampe fundet i dette vindue.")
        continue
    kamp = data[0]
    print(f"Eksempel-kamp: {kamp['home_team']} vs {kamp['away_team']} ({kamp['commence_time']})")
    for bm in kamp["bookmakers"]:
        if bm["key"] in ("unibet_eu", "unibet_nl", "unibet_se", "nordicbet"):
            market_keys = [m["key"] for m in bm["markets"]]
            print(f"  {bm['title']} ({bm['key']}): markeder = {market_keys}")

print("\nRemaining requests:", resp.headers.get("x-requests-remaining"))
