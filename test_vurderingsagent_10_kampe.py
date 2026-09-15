"""
Test af de 10 empiriske testkampe (5 Big 5-ligaer x 2 markeder) mod hele
kaeden Data -> Analyse -> Transparens -> Vurdering, med saerligt fokus paa
at maale om Vurderingsagentens nye Lav/Mellem/Hoej-kategorisering
(grundlagskvalitet, se agents/vurderingsagent.py) klumper sig i én
kategori, eller om den reelt varierer paa tvaers af rigtige kampe - jf.
projektloggens "Vurderingsagentens Lav/Mellem/Hoej-kategorisering",
ANBEFALING TIL BRUGER.

IKKE en del af produktkoden - scratch-fil, samme princip som
test_dataagent_end_to_end.py.

MAA KOERES DIREKTE PAA DIN MASKINE I DIN EGEN TERMINAL (IKKE via Cowork) -
Cowork's device-bridge-sandbox har IKKE netvaerksadgang til
football-data.org/The Odds API/Firecrawl.dev/Anthropic, saa scriptet kan
ikke koeres herfra. Aktiver venv foerst:

    source venv/bin/activate
    python3 test_vurderingsagent_10_kampe.py

Bruger RIGTIGE API-kald og reelt credits/quota: Odds API (10 kald, ét pr.
liga+marked-kombination, billigt jf. Dataagentens dokumenterede
credit-model), football-data.org, Firecrawl.dev (op til 10 kald), og
Anthropic Haiku (kun for kampe hvor Firecrawl reelt fandt >0 nyheder,
jf. Analyseagentens deterministiske 0-kilder-genvej).

rens_tekst() anvendes bevidst paa hver nyheds "beskrivelse" foer den sendes
til Analyseagenten (jf. dataagent.py's egen docstring: rens_tekst loeser
stoej-problemet, IKKE relevans - det er Analyseagentens ansvar). Dette er
IKKE gjort i test_dataagent_end_to_end.py (som kun tester Dataagenten
isoleret), men boer vaere en del af den kommende app.py-wiring.
"""
import sys
from collections import Counter

sys.path.insert(0, ".")

from agents.dataagent import vaelg_kamp, hent_nyheder, rens_tekst, FALLBACK_BESKED, DataagentFejl
from agents.analyseagent import analyser_nyheder, AnalyseagentFejl
from agents.transparensagent import byg_risikobillede
from agents.vurderingsagent import byg_bet_assessment, bestem_grundlagskvalitet

LIGAER = ["Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1"]
MARKEDER = ["Asian Handicap", "Over/Under 2.5"]


def koer():
    resultater = []
    kategori_fordeling = Counter()

    for liga in LIGAER:
        for marked in MARKEDER:
            print(f"\n{'=' * 70}\n{liga} — {marked}\n{'=' * 70}")

            try:
                kamp = vaelg_kamp(liga, marked)
            except DataagentFejl as e:
                print(f"DataagentFejl ved vaelg_kamp: {e}")
                resultater.append({"liga": liga, "marked": marked, "status": "dataagent_fejl"})
                continue

            if kamp == FALLBACK_BESKED:
                print("Ingen kamp fundet i det rullende 7-dages-vindue.")
                resultater.append({"liga": liga, "marked": marked, "status": "ingen_kamp"})
                continue

            if kamp.get("odds") is None:
                print(f"{kamp['hjemmehold']} vs {kamp['udehold']}: ingen odds matchet (holdnavne-mismatch eller manglende bogmagerdaekning), springer over.")
                resultater.append({"liga": liga, "marked": marked, "status": "ingen_odds"})
                continue

            try:
                nyheder_raa = hent_nyheder(kamp["hjemmehold"], kamp["udehold"])
            except DataagentFejl as e:
                print(f"DataagentFejl ved hent_nyheder: {e}")
                resultater.append({"liga": liga, "marked": marked, "status": "nyheder_fejl"})
                continue

            nyheder = [
                {**n, "beskrivelse": rens_tekst(n.get("beskrivelse"))}
                for n in nyheder_raa
            ]

            try:
                kontekst = analyser_nyheder(kamp["hjemmehold"], kamp["udehold"], nyheder)
            except AnalyseagentFejl as e:
                print(f"AnalyseagentFejl: {e}")
                resultater.append({"liga": liga, "marked": marked, "status": "analyse_fejl", "fejl": str(e)})
                continue

            risikobillede = byg_risikobillede(kamp, kontekst)
            kort = byg_bet_assessment(risikobillede)
            kategori = bestem_grundlagskvalitet(kontekst)

            print(kort)
            print(f"\n>>> Grundlagskvalitet-kategori: {kategori}")

            kategori_fordeling[kategori] += 1
            resultater.append({
                "liga": liga,
                "marked": marked,
                "status": "ok",
                "kamp": f"{kamp['hjemmehold']} vs {kamp['udehold']}",
                "kilder_i_alt": kontekst["kilder_i_alt"],
                "kilder_relevante": kontekst["kilder_vurderet_relevante"],
                "kategori": kategori,
            })

    print(f"\n\n{'=' * 70}\nSAMLET FORDELING AF GRUNDLAGSKVALITET ({sum(kategori_fordeling.values())} kampe med gyldigt resultat ud af {len(LIGAER) * len(MARKEDER)} kombinationer)\n{'=' * 70}")
    for kat in ["Høj", "Mellem", "Lav"]:
        print(f"  {kat}: {kategori_fordeling.get(kat, 0)}")

    ingen_kamp = sum(1 for r in resultater if r["status"] == "ingen_kamp")
    ingen_odds = sum(1 for r in resultater if r["status"] == "ingen_odds")
    fejl = sum(1 for r in resultater if r["status"] in ("dataagent_fejl", "nyheder_fejl", "analyse_fejl"))
    print(f"\n  Ingen kamp i vindue: {ingen_kamp}")
    print(f"  Ingen odds matchet: {ingen_odds}")
    print(f"  Fejl undervejs: {fejl}")

    antal_kategorier_set = len(kategori_fordeling)
    total_ok = sum(kategori_fordeling.values())
    if total_ok == 0:
        print("\n  INGEN gyldige resultater — kan ikke konkludere noget om klump-problemet. Tjek fejl ovenfor.")
    elif antal_kategorier_set == 1:
        print(f"\n  ADVARSEL: ALLE {total_ok} kampe med resultat landede i samme kategori ('{list(kategori_fordeling.keys())[0]}'). Klump-problemet er IKKE løst af kildedækning alene på dette udsnit — overvej mulighed E (ny ekstern datakilde) eller udvid testen med flere kampe/dage.")
    else:
        print(f"\n  Reel variation observeret på tværs af {antal_kategorier_set} kategorier ud af {total_ok} kampe. Kildedækning-tilgangen ser ud til at give reel diskriminering på dette udsnit — men n={total_ok} er stadig lille; gentag gerne på en anden dag/uge før det konkluderes endeligt.")

    return resultater


if __name__ == "__main__":
    koer()
