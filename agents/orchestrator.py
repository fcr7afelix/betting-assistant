"""
Orchestrator - dialog-laget.
Al styring af agent-rækkefølge (Data -> Analyse -> Værdi/Risiko -> Beslutning)
sker i app.py som almindelig Python-kontrolflow - IKKE her.
Denne fil indeholder KUN den ene reelle prompt i systemet: dialogen med brugeren.
"""

import os
import re
import json
import datetime
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = """Du er en dialogassistent for en betting-rådgivningsplatform. Dette
er en midlertidig backup-version, der udelukkende giver forslag til
landskampe fra UEFA Nations League, aktiveret fordi Big 5-ligaerne holder
landskampspause i denne periode.

Din opgave er UDELUKKENDE at afklare tre ting med brugeren gennem naturlig samtale:
1. Liga
2. Marked (Asian Handicap eller Over/Under 2.5)
3. Indsats (beløb i kr.)

Du må IKKE selv vurdere kampe, beregne odds eller anbefale væddemål - det gør andre
systemer efter dig. Når alle tre er afklaret, opsummér dem og bed EKSPLICIT om
bekræftelse fra brugeren, FØR du kalder funktionen "afklaring_fuldfoert".

Forklar kort, hvorfor du spørger til det, du spørger om. Undgå at presse brugeren
mod bestemte valg - dit formål er at afklare præferencer, ikke overtale.

Hvis brugeren IKKE bekræfter opsummeringen (fx retter et felt, siger nej, eller er i
tvivl), må du IKKE kalde funktionen "afklaring_fuldfoert". Spørg i stedet konkret,
hvilket felt der skal rettes, opdatér kun det felt, opsummér alle tre felter igen
(inkl. de uændrede), og bed om bekræftelse på ny, før du kalder funktionen.

Når du spørger til indsatsen, hold spørgsmålet kort og ligetil - giv IKKE en
parentetisk liste af eksempelbeløb (undgå fx "(50 kr, 100 kr, 500 kr osv.)").

Hvis brugeren signalerer lavt forhåndskendskab til et felt (fx "ved ikke",
"aner det ikke", "hvad betyder det", "forstår ikke forskellen"), må du IKKE
blot gentage det samme spørgsmål uændret. Giv i stedet en kort, konkret
forklaring med ét opfundet taleksempel (fx for Asian Handicap: "Det betyder,
at det ene hold får et forspring i det matematiske resultat, fx -1.5 mål -
så skal holdet vinde med mindst 2 mål, for at væddemålet vinder"), og spørg
derefter igen.

Skriv UDELUKKENDE på naturligt, korrekt dansk. Undgå aktivt norsk- eller
svensk-farvede ord og vendinger, selv når de ligner dansk - fx skriv
"holdet", ALDRIG "laget"; skriv "topfodboldmesterskab", ALDRIG
"toppfotballsmesterskab". Hvis du er i tvivl, om et ord er korrekt dansk,
vælg et andet, mere almindeligt dansk ord."""

AFKLARING_TOOL = {
    "name": "afklaring_fuldfoert",
    "description": "Kaldes KUN efter brugeren har bekræftet alle tre felter.",
    "input_schema": {
        "type": "object",
        "properties": {
            "liga": {
                "type": "string",
                "enum": ["UEFA Nations League"],
            },
            "marked": {"type": "string", "enum": ["Asian Handicap", "Over/Under 2.5"]},
            "indsats": {"type": "number", "description": "Indsats i kroner"},
        },
        "required": ["liga", "marked", "indsats"],
    },
}

# Deterministisk ikon-indsættelse - IKKE overladt til sprogmodellens generering,
# samme princip som ansvarligt-spil-disclaimeren. Lukket, enum-begrænset sæt
# (5 ligaer, 2 markeder) gør 1:1-mapping mulig.
LIGA_IKONER = {
    "UEFA Nations League": "🏆",
}
MARKED_IKONER = {
    "Asian Handicap": "⚖️",
    "Over/Under 2.5": "↕️",
}


# Bred emoji-detektion - bruges til at fjerne ALLE emoji, Haiku selv måtte
# generere, så kun vores kontrollerede, deterministiske ikonsæt vises.
_EMOJI_MOENSTER = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symboler & piktogrammer
    "\U0001F680-\U0001F6FF"  # transport
    "\U0001F1E0-\U0001F1FF"  # flag (regionale indikatorer)
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F900-\U0001F9FF"  # supplerende symboler
    "\U00002600-\U000026FF"  # diverse symboler (bl.a. ⚖)
    "\U0001FA70-\U0001FAFF"
    "\U00002190-\U000021FF"  # pile (bl.a. ↕)
    "\U0000FE00-\U0000FE0F"  # variationsselektorer
    "]+",
    flags=re.UNICODE,
)


def tilfoej_ikoner(tekst):
    """Indsætter deterministisk et fast ikon efter kendte liga-/marked-navne og
    kronebeløb i en tekststreng. Køres på al tekst, FØR den vises til brugeren
    eller gemmes i transskriptet - aldrig på det, der sendes tilbage til
    sprogmodellen som samtalehistorik.

    Fremgangsmåde: (1) fjern FØRST alle emoji, Haiku selv måtte have genereret
    (uanset om det er vores egne eller andre, fx 📊 👍) - kun vores kodestyrede
    mapping skal bestemme, hvilke ikoner der vises, (2) indsæt derefter vores
    ikoner deterministisk efter hvert navn/beløb."""
    tekst = _EMOJI_MOENSTER.sub("", tekst)
    tekst = re.sub(r"[ \t]{2,}", " ", tekst)
    tekst = re.sub(r"[ \t]+\n", "\n", tekst)
    tekst = re.sub(r"[ \t]+$", "", tekst, flags=re.MULTILINE)

    for navn, ikon in {**LIGA_IKONER, **MARKED_IKONER}.items():
        tekst = re.sub(
            rf'({re.escape(navn)})(\*{{0,2}})',
            rf'\1\2 {ikon}',
            tekst,
        )
    tekst = re.sub(r'(\d+([.,]\d+)?\s*kr\.?)', rf'\1 💰', tekst)
    return tekst


# Deterministisk validering/ansvarligt-spil-grænse for indsatsen - kodestyret,
# IKKE overladt til Haikus egen vurdering (samme princip som ikon-funktionen
# og ansvarligt-spil-disclaimeren på det endelige forslag).
GRAENSE_HOEJ_INDSATS = 1000
HOEJ_INDSATS_BESKED = (
    "Dit anmodede indsatsbeløb er sat ret højt! Spil med omtanke. "
    "Og spil aldrig for mere, end du har råd til at tabe!"
)

# TILFOEJET 2026-09-18 (punkt 1 i den samlede promptrevision, se
# projekt-ramme-betting-agent.md's "Den ene, samlede promptrevision"):
# 4 ud af 5 usability-testpersoner saa ALDRIG en ansvarligt-spil-besked,
# fordi den hidtil KUN blev vist ved indsats > GRAENSE_HOEJ_INDSATS. Denne
# BASISTEKST vises nu UBETINGET (Streamlit-header-banner + hvert bet
# assessment-kort) - HOEJ_INDSATS_BESKED ovenfor er BEVIDST bevaret
# UAEndret og fortsat kun vist ved hoej indsats: den er kontekstuelt
# specifik ("dit beloeb er sat REt hoejt") og ville vaere faktuelt forkert
# at vise ved en lav indsats. De to beskeder er derfor et LAG, ikke en
# erstatning af hinanden - begge stadig 100% kodestyrede, 0 LLM-beslutning.
ANSVARLIGT_SPIL_BASISTEKST = (
    "Spil med omtanke. Spil aldrig for mere, end du har råd til at tabe."
)

# TILFOEJET 2026-09-18 (bruger-feedback efter foerste live-test): den
# generiske basistekst alene manglede konkrete, danske hjaelperessourcer
# paa selve kortet (kun tilstede som ren opfordring, ingen henvisning).
# Begge domaener er verificeret som RIGTIGE, gaeldende danske ressourcer
# under Spillemyndigheden (ikke opdigtede): StopSpillet.dk (raadgivning om
# spilafhaengighed) og ROFUS.nu (Spillemyndighedens register for frivilligt
# selvudelukkede spillere). Vises KUN paa selve kortet (ikke i det
# koertere header-banner, som brugeren bekraeftede allerede var fint).
ANSVARLIGT_SPIL_KORT_TILLAEG = (
    "Spillemyndighedens Hjælpelinje: StopSpillet.dk | "
    "Selvudelukkelse: ROFUS.nu | Spil Ansvarligt | 18+"
)


def valider_indsats(indsats):
    """Returnerer en fejlbesked (str), hvis indsatsen er ugyldig, ellers None.
    Kaldes FØR en afklaring accepteres som fuldført - Haiku kan ikke omgå
    denne kontrol, uanset hvad tool-kaldet indeholder."""
    if not isinstance(indsats, (int, float)) or indsats <= 0:
        return "Indsatsen skal være et positivt beløb større end 0 kr. Spørg brugeren om et gyldigt beløb igen."
    return None


def save_transcript(session_id, messages, afklaring):
    """Gemmer sessionens fulde dialog + resultat til en JSON-fil.
    session_id skal være et anonymt løbenummer (fx 'test-01'), ALDRIG
    testpersonens navn - se note om anonymisering."""
    serializable_messages = []
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            # Indhold kan enten være rigtige SDK-blokke fra Haikus svar (har
            # attributter som b.type) ELLER almindelige dicts, vi selv har
            # bygget (fx en tool_result-fejlbesked ved afvist indsats) - de to
            # skal serialiseres forskelligt.
            content = [
                b if isinstance(b, dict) else {
                    "type": b.type,
                    "text": tilfoej_ikoner(b.text) if getattr(b, "text", None) else getattr(b, "text", None),
                    "input": getattr(b, "input", None),
                }
                for b in content
            ]
        serializable_messages.append({"role": m["role"], "content": content})

    log_entry = {
        "session_id": session_id,
        "timestamp": datetime.datetime.now().isoformat(),
        "messages": serializable_messages,
        "afklaring": afklaring,
    }
    log_path = LOG_DIR / f"session_{session_id}.json"
    log_path.write_text(json.dumps(log_entry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Transskript gemt: {log_path}]")


def run_dialog(session_id="dev"):
    """Kører dialogen i terminalen (CLI-testmode). Returnerer den afklarede
    forespørgsel som dict, når brugeren har bekræftet alle tre felter."""
    messages = []
    print("Assistent:", tilfoej_ikoner("Hej! Lad os finde et forslag til dig. Hvilken liga interesserer dig? (Premier League, Serie A, La Liga, Bundesliga eller Ligue 1)"))

    afventer_tool_result = False  # True lige efter en afvist indsats - da skal
    # modellen svare på fejlen FØR vi beder om ny brugerinput (API'et kræver
    # skiftevis user/assistant - to user-beskeder i træk er ikke gyldigt).

    while True:
        if not afventer_tool_result:
            user_input = input("Dig: ")
            messages.append({"role": "user", "content": user_input})
        afventer_tool_result = False

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[AFKLARING_TOOL],
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        text_blocks = [b.text for b in response.content if b.type == "text"]
        if text_blocks:
            print("Assistent:", tilfoej_ikoner(" ".join(text_blocks)))

        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block:
            afklaring = tool_use_block.input
            fejl = valider_indsats(afklaring.get("indsats"))
            if fejl:
                # Ugyldig indsats - afvis deterministisk, send tool_result med
                # fejlbesked tilbage til modellen, og lad MODELLEN svare på
                # den (ikke brugeren) i næste loop-iteration.
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_block.id,
                            "content": fejl,
                            "is_error": True,
                        }
                    ],
                })
                afventer_tool_result = True
                continue

            print("\n[Afklaring fuldført]:", json.dumps(afklaring, ensure_ascii=False, indent=2))
            if afklaring["indsats"] > GRAENSE_HOEJ_INDSATS:
                print(f"[Info] {HOEJ_INDSATS_BESKED}")
            save_transcript(session_id, messages, afklaring)
            return afklaring


if __name__ == "__main__":
    run_dialog()
