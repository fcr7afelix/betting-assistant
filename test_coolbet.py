import os
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
key = os.environ.get("ODDS_API_KEY")

leagues = ["soccer_epl", "soccer_france_ligue_one", "soccer_germany_bundesliga",
           "soccer_italy_serie_a", "soccer_spain_la_liga"]

for liga in leagues:
    resp = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{liga}/odds",
        params={"apiKey": key, "regions": "eu", "markets": "spreads,totals,h2h", "oddsFormat": "decimal"},
    )
    data = resp.json()
    print(f"\n=== {liga} ===")
    if not data:
        print("Ingen kampe.")
        continue
    for kamp in data[:3]:
        cb = next((b for b in kamp["bookmakers"] if b["key"] == "coolbet"), None)
        markets = [m["key"] for m in cb["markets"]] if cb else "IKKE TIL STEDE"
        print(f"  {kamp['home_team']} vs {kamp['away_team']}: Coolbet = {markets}")

print("\nRemaining:", resp.headers.get("x-requests-remaining"))
