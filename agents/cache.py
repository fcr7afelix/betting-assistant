"""
Simpel fil-baseret cache med TTL (time-to-live), bygget for at spare paa
football-data.org's (10 kald/min) og navnlig The Odds API's (500 credits/md)
kvoter under kommende dev-iteration paa Analyse- og Vaerdi/Risikoagenten.

Bevidst simpelt design: JSON-filer paa disk, noeglet paa en hash af en
menneskelaeselig streng - INGEN database, ingen samtidighedskontrol
(flere processer, der skriver til samme noegle paa samme tid, kan i teorien
overskrive hinanden - accepteret risiko for et enkeltbruger-devtool, IKKE
egnet til en flerbruger-produktionssituation)."""
import hashlib
import json
import os
import time

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


def _cache_sti(noegle):
    os.makedirs(CACHE_DIR, exist_ok=True)
    hash_ = hashlib.sha256(noegle.encode("utf-8")).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{hash_}.json")


def hent_med_cache(noegle, ttl_sekunder, hent_fn):
    """Returnerer cachet data for `noegle`, hvis den findes og er yngre end
    `ttl_sekunder`; ellers kaldes `hent_fn()` (det RIGTIGE, dyre API-kald),
    resultatet caches, og returneres. `hent_fn`s returvaerdi SKAL vaere
    JSON-serialiserbar (ingen tuple-noegler i dicts, ingen datetime-objekter
    - se dataagent.py's hent_odds() for et eksempel paa at omgaa dette ved at
    returnere en liste af dicts i stedet for en dict med tuple-noegler)."""
    sti = _cache_sti(noegle)
    if os.path.exists(sti):
        try:
            with open(sti, "r", encoding="utf-8") as f:
                indpakket = json.load(f)
            alder = time.time() - indpakket["tidsstempel"]
            if alder < ttl_sekunder:
                return indpakket["data"]
        except (json.JSONDecodeError, KeyError, OSError):
            # Korrupt eller ulaeselig cache-fil - ignorer og hent paa ny,
            # frem for at crashe paa en ren infrastruktur-detalje.
            pass

    data = hent_fn()
    try:
        with open(sti, "w", encoding="utf-8") as f:
            json.dump({"tidsstempel": time.time(), "noegle": noegle, "data": data}, f)
    except OSError:
        # Cache-skrivning fejlede (fx disk fuld) - ikke kritisk, fortsaet
        # uden cache frem for at lade en sekundaer fejl vaelte hovedkaldet.
        pass
    return data
