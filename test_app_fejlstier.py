"""
Manuel visuel test af app.py's to fejl-/fallback-stier - tilfojet 2026-09-08
som svar pa brugerens sporgsmal ("Jeg testede ogsa Prem League (Leeds v
Newcastle) - ved ikke om det er en kamp fra testscript'et. Hvordan tester vi
de to fejl-/fallback-stier?").

VIRKEMADE: monkeypatcher agents.dataagent.vaelg_kamp FOR app.py importeres,
sa app.py's "from agents.dataagent import vaelg_kamp" binder til den falske
funktion (Pythons "from X import navn" slar navnet op paa modulet PAA
IMPORTTIDSPUNKTET - patcher vi modulattributten foerst, faar app.py den
patchede version, helt uden at aendre en linje i app.py selv).

Styres af miljovariablen FEJLSTI (saettes FOR streamlit koeres):
  FEJLSTI=fallback   -> simulerer at Dataagenten ikke fandt NOGEN kamp
                         (FALLBACK_BESKED-stien, dataagent.py's egen
                         "ingen kamp tilgaengelig i perioden"-tilfaelde)
  FEJLSTI=ingen_odds -> simulerer at en kamp blev fundet, men uden odds for
                         det valgte marked (kamp["odds"] is None-stien)
  (ikke saet FEJLSTI) -> normal, urort opforsel - kalder den rigtige
                         vaelg_kamp() (kraever rigtig netvaerksadgang)

BRUG (kor i din egen terminal, IKKE via Cowork - se projektloggens
"Miljobegraensning: netvaerksadgang" for hvorfor):
  source venv/bin/activate
  FEJLSTI=fallback   streamlit run test_app_fejlstier.py
  FEJLSTI=ingen_odds streamlit run test_app_fejlstier.py

I begge tilfaelde: skriv en gyldig liga/marked/indsats i chatten som normalt
(fx "Premier League, Asian Handicap, 100 kr") - Orchestratorens dialog-lag er
UROERT af denne test, saa selve afklaringsflowet er 100% det rigtige. Det er
KUN _byg_forslag()'s forste skridt (vaelg_kamp) der er erstattet, saa du kan
se PRAECIS den besked/det UI-flow, brugeren selv ville se i hver fejlsti,
uden at skulle vente pa eller ramme den rigtige fejl tilfaeldigt i naturen.
"""
import os
import sys

FEJLSTI = os.environ.get("FEJLSTI")

if FEJLSTI:
    import agents.dataagent as dataagent_modul

    if FEJLSTI == "fallback":
        def _falsk_vaelg_kamp(liga, marked, dage_frem=7):
            return dataagent_modul.FALLBACK_BESKED
    elif FEJLSTI == "ingen_odds":
        def _falsk_vaelg_kamp(liga, marked, dage_frem=7):
            return {
                "hjemmehold": "Testhold A",
                "udehold": "Testhold B",
                "kickoff_utc": "2026-09-15T18:00:00Z",
                "odds": None,
            }
    else:
        print(f"Ukendt FEJLSTI-vaerdi: {FEJLSTI!r} (brug 'fallback' eller 'ingen_odds')")
        sys.exit(1)

    dataagent_modul.vaelg_kamp = _falsk_vaelg_kamp

# Kor selve app.py's kode i dette script's namespace - simplest mulige maade
# at genbruge HELE app.py's UI-flow uden at aendre app.py selv. Fordi
# patchningen ovenfor sker FOR denne exec, fanger app.py's egen
# "from agents.dataagent import vaelg_kamp" den patchede funktion.
with open("app.py", encoding="utf-8") as f:
    kode = f.read()
exec(compile(kode, "app.py", "exec"), {"__name__": "__main__"})
