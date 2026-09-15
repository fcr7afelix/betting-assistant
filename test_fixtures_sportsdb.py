import requests
from datetime import datetime, timedelta, timezone

leagues = {
    "Premier League": "4328",
    "Serie A": "4332",
    "La Liga": "4335",
    "Bundesliga": "4331",
    "Ligue 1": "4334",
}

now = datetime.now(timezone.utc)
window_end = now + timedelta(days=7)

for navn, liga_id in leagues.items():
    resp = requests.get(f"https://www.thesportsdb.com/api/v1/json/123/eventsnextleague.php?id={liga_id}")
    print(f"\n=== {navn} (id={liga_id}) — status {resp.status_code} ===")
    data = resp.json()
    events = data.get("events") or []
    print(f"Antal kampe returneret i alt: {len(events)}")

    indenfor_vindue = []
    for e in events:
        dato_str = e.get("dateEvent")
        tid_str = e.get("strTime") or "00:00:00"
        if not dato_str:
            continue
        try:
            kickoff = datetime.strptime(f"{dato_str} {tid_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if now <= kickoff <= window_end:
            indenfor_vindue.append((kickoff, e["strHomeTeam"], e["strAwayTeam"]))

    print(f"Kampe inden for rullende 7-dages-vindue: {len(indenfor_vindue)}")
    for kickoff, hjemme, ude in sorted(indenfor_vindue):
        print(f"  {kickoff.isoformat()}  {hjemme} vs {ude}")
