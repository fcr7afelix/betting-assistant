import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
key = os.environ.get("ODDS_API_KEY")

if not key:
    print("FEJL: ODDS_API_KEY ikke fundet i .env")
else:
    resp = requests.get(
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
        params={
            "apiKey": key,
            "regions": "eu",
            "markets": "spreads,totals,h2h",
            "oddsFormat": "decimal",
        },
    )
    print("Status:", resp.status_code)
    print("Remaining requests:", resp.headers.get("x-requests-remaining"))
    print("Used requests:", resp.headers.get("x-requests-used"))
    data = resp.json()
    print(json.dumps(data[:2] if isinstance(data, list) else data, indent=2, ensure_ascii=False))
