import os
import requests
import json
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
key = os.environ.get("FOOTBALL_DATA_KEY")

today = date.today()
in_7_days = today + timedelta(days=7)

resp = requests.get(
    "https://api.football-data.org/v4/competitions/PL/matches",
    headers={"X-Auth-Token": key},
    params={"dateFrom": today.isoformat(), "dateTo": in_7_days.isoformat()},
)
print("Status:", resp.status_code)
data = resp.json()
if resp.status_code != 200:
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    matches = data.get("matches", [])
    print(f"Antal kampe i vinduet: {len(matches)}")
    for m in matches[:5]:
        print(f"  {m['utcDate']}  {m['homeTeam']['name']} vs {m['awayTeam']['name']}  status={m['status']}")
