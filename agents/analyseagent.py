"""
Analyseagenten: fortolker Dataagentens raa nyhedstekst (Firecrawl) kvalitativt -
form, skader, kontekst - og frasorterer stoej/irrelevante resultater ud fra
egen sprogforstaaelse. LAAST krav (jf. projektloggens "Firecrawl-udbyder-
validering"): haandterer EKSPLICIT 0 relevante resultater aerligt, i stedet
for at hallucinere relevans ud af stoej.

Dette er systemets ENESTE oevrige LLM-kald ud over Orchestratorens dialoglag -
ét enkelt, ikke-dialogisk kald pr. kamp, med tvunget tool-use (samme JSON-via-
tool-use-moenster som Orchestratoren), saa outputtet altid er strengt
struktureret og aldrig fri tekst, Transparensagenten skal fortolke selv.
"""
import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-haiku-4-5"

# Loftet paa antal fund matcher Bet Assessment-kortets layout (LAAST design,
# se projektloggen) - flere end 3 fund goer kortet uoverskueligt, ikke mere
# "grundigt".
MAKS_FUND = 3


class AnalyseagentFejl(Exception):
    """Samler alle Anthropic API-fejl fra Analyseagenten i én type, samme
    princip som Dataagentens DataagentFejl - ét sted at haandtere fejl i det
    kommende UI-lag, ikke fanget internt her."""
    pass


SYSTEM_PROMPT = """Du analyserer nyhedsresultater om en kommende fodboldkamp for at
finde faktorer, der er relevante for en vurdering af kampen (form, skader,
opstillinger, kontekst) - IKKE for at forudsige et resultat eller anbefale et
væddemål.

Du faar en liste af søgeresultater (titel, url, beskrivelse). Mange af disse
resultater er STØJ og IKKE relevante for netop denne kamp - det kan være
indhold om andre klubber, sociale medier-opslag, eller forældet materiale.
Din vigtigste opgave er at frasortere støj, IKKE at finde noget for enhver
pris.

Regler:
1. Brug UDELUKKENDE oplysninger, der faktisk staar i de leverede resultater.
   Opfind ALDRIG en faktor, der ikke er direkte understøttet af teksten.
   Dette gaelder OGSAA konkrete tal (fx tabelplacering, pointtal, statistik):
   gengiv et tal KUN hvis det staar ordret eller entydigt i kildeteksten -
   gaet ALDRIG et tal, selv et der lyder plausibelt.
2. Hvis INGEN af resultaterne er relevante for kampen, skal du returnere en
   TOM liste af fund og sætte kilder_vurderet_relevante til 0. Sig det ærligt
   - forsøg ALDRIG at konstruere relevans ud af irrelevant materiale for at
   have noget at rapportere.
3. Returnér højst 3 fund, som korte, konkrete saetninger.
4. Hvis materialet peger paa noget, der kunne aendre vurderingen igen inden
   kampstart (fx en usikker opstilling, en skade under afklaring), saet det
   som usikkerhedspunkt. Findes intet saadant i materialet, saet det til null
   - opfind det ikke.
5. Kildeteksten (fra Firecrawl) er OFTE stoejet, ufuldstaendig eller daarligt
   formateret. Skriv ALLIGEVEL hvert fund som en fuldstaendig, grammatisk
   korrekt daensk saetning - opfind ALDRIG et ord eller sammensat ord, der
   ikke findes i det daenske sprog, for at "faa saetningen til at haenge
   sammen" (fx paafundne ord som "ekstremist" om en spiller, eller
   "hjemmepointerede" - saadanne ord findes ikke og maa ALDRIG bruges). Er
   kildeteksten for utydelig eller stoejet til at kunne omskrives til en
   klar, korrekt saetning, UDELAD den detalje helt fremfor at gaette dig
   frem til noget uforstaaeligt.
6. Skriv UDELUKKENDE paa naturligt, korrekt dansk. Undgaa aktivt norsk- eller
   svensk-farvede ord og vendinger, selv naar de ligner dansk.

Kald altid funktionen "aflever_analyse" med dit resultat."""

ANALYSE_TOOL = {
    "name": "aflever_analyse",
    "description": "Afleverer den strukturerede analyse af nyhedsresultaterne.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fund": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAKS_FUND,
                "description": "0-3 korte, konkrete faktorer, udelukkende baseret på de leverede resultater. Tom liste hvis intet er relevant.",
            },
            "kilder_vurderet_relevante": {
                "type": "integer",
                "description": "Hvor mange af de leverede søgeresultater var faktisk relevante for kampen.",
            },
            "usikkerhedspunkt": {
                "type": ["string", "null"],
                "description": "Én kort saetning om noget, der kunne aendre vurderingen - eller null, hvis intet saadant findes i materialet.",
            },
        },
        "required": ["fund", "kilder_vurderet_relevante", "usikkerhedspunkt"],
    },
}


def _formater_nyheder_til_prompt(nyheder):
    """Bygger den menneskelaesbare liste af soegeresultater, modellen skal
    vurdere. Ren tekstformatering, ingen fortolkning."""
    linjer = []
    for i, n in enumerate(nyheder, start=1):
        titel = n.get("titel") or "(ingen titel)"
        beskrivelse = n.get("beskrivelse") or "(ingen beskrivelse)"
        url = n.get("url") or "(ingen url)"
        linjer.append(f"{i}. Titel: {titel}\n   Beskrivelse: {beskrivelse}\n   URL: {url}")
    return "\n\n".join(linjer)


def analyser_nyheder(hjemmehold, udehold, nyheder):
    """Analyserer Dataagentens raa nyhedsresultater for kampen
    hjemmehold-udehold. Returnerer ALTID et dict med samme facon:
    {"fund": [...], "kilder_vurderet_relevante": int, "kilder_i_alt": int,
     "usikkerhedspunkt": str | None}.

    Deterministisk genvej (INGEN LLM-kald, sparer credits): hvis Dataagenten
    allerede returnerede 0 nyheder, er der intet at analysere - vi ved
    allerede, at der er 0 relevante resultater, uden at spørge Haiku om det.
    """
    kilder_i_alt = len(nyheder)
    if kilder_i_alt == 0:
        return {
            "fund": [],
            "kilder_vurderet_relevante": 0,
            "kilder_i_alt": 0,
            "usikkerhedspunkt": None,
        }

    bruger_besked = (
        f"Kommende kamp: {hjemmehold} vs {udehold}.\n\n"
        f"Søgeresultater ({kilder_i_alt} i alt):\n\n"
        f"{_formater_nyheder_til_prompt(nyheder)}"
    )

    try:
        respons = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[ANALYSE_TOOL],
            tool_choice={"type": "tool", "name": "aflever_analyse"},
            messages=[{"role": "user", "content": bruger_besked}],
        )
    except Exception as e:
        raise AnalyseagentFejl(
            f"Kunne ikke analysere nyheder for {hjemmehold} vs {udehold}: {e}"
        )

    tool_use_block = next((b for b in respons.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        # tool_choice tvinger et tool-kald, men Anthropic-SDK'ens kontrakt
        # garanterer det ikke 100% (fx ved et afkortet svar) - fail ærligt
        # frem for at antage en tom analyse.
        raise AnalyseagentFejl(
            f"Analyseagenten fik intet strukturet svar for {hjemmehold} vs {udehold}."
        )

    analyse = tool_use_block.input
    fund = analyse.get("fund", [])[:MAKS_FUND]
    kilder_vurderet_relevante = analyse.get("kilder_vurderet_relevante", 0)
    # KONSISTENS-RETTELSE (tilfoejet 2026-09-08, se projektloggens "De 10
    # empiriske testkampe"): Haiku returnerede i mindst ét reelt testtilfaelde
    # et kilder_vurderet_relevante-tal, der var LAVERE end antallet af
    # konkrete fund i samme svar (fx "2 af 5 relevante" med 3 nummererede
    # fund) - en model-inkonsistens, ikke en kodefejl. Rettet deterministisk:
    # tallet kan aldrig vaere lavere end det faktiske antal fund, vi rent
    # faktisk viderestiller.
    kilder_vurderet_relevante = max(kilder_vurderet_relevante, len(fund))
    return {
        "fund": fund,
        "kilder_vurderet_relevante": kilder_vurderet_relevante,
        "kilder_i_alt": kilder_i_alt,
        "usikkerhedspunkt": analyse.get("usikkerhedspunkt"),
    }
