import os
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
key = os.environ.get("FOOTBALL_DATA_KEY")

today = date.today()
in_7_days = today + timedelta(days=7)
spilleklar_status = {"SCHEDULED", "TIMED"}

codes = {"PL": "Premier League", "FL1": "Ligue 1", "BL1": "Bundesliga", "SA": "Serie A", "PD": "La Liga"}

for code, navn in codes.items():
    resp = requests.get(
        f"https://api.football-data.org/v4/competitions/{code}/matches",
        headers={"X-Auth-Token": key},
        params={"dateFrom": today.isoformat(), "dateTo": in_7_days.isoformat()},
    )
    data = resp.json()
    matches = data.get("matches", [])
    spilleklar = [m for m in matches if m["status"] in spilleklar_status]
    andre_status = set(m["status"] for m in matches) - spilleklar_status
    print(f"{navn} ({code}): {len(matches)} kampe total, {len(spilleklar)} spilleklare")
    if andre_status:
        print(f"  Andre statusser set: {andre_status}")
