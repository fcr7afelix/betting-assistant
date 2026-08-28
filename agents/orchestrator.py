"""
Orchestrator - dialog-laget.
Al styring af agent-rækkefølge (Data -> Analyse -> Værdi/Risiko -> Beslutning)
sker i app.py som almindelig Python-kontrolflow - IKKE her.
Denne fil indeholder KUN den ene reelle prompt i systemet: dialogen med brugeren.
"""

import os
import json
import datetime
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

SYSTEM_PROMPT = """Du er en dialogassistent for en betting-rådgivningsplatform.

Din opgave er UDELUKKENDE at afklare tre ting med brugeren gennem naturlig samtale:
1. Sportsgren
2. Marked (Asian Handicap eller Over/Under 2.5)
3. Indsats (beløb i kr.)

Du må IKKE selv vurdere kampe, beregne odds eller anbefale væddemål - det gør andre
systemer efter dig. Når alle tre er afklaret, opsummér dem og bed EKSPLICIT om
bekræftelse fra brugeren, FØR du kalder funktionen "afklaring_fuldfoert".

Forklar kort, hvorfor du spørger til det, du spørger om. Undgå at presse brugeren
mod bestemte valg - dit formål er at afklare præferencer, ikke overtale."""

AFKLARING_TOOL = {
    "name": "afklaring_fuldfoert",
    "description": "Kaldes KUN efter brugeren har bekræftet alle tre felter.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sport": {"type": "string", "description": "Den valgte sportsgren, fx fodbold"},
            "marked": {"type": "string", "enum": ["Asian Handicap", "Over/Under 2.5"]},
            "indsats": {"type": "number", "description": "Indsats i kroner"},
        },
        "required": ["sport", "marked", "indsats"],
    },
}


def save_transcript(session_id, messages, afklaring):
    """Gemmer sessionens fulde dialog + resultat til en JSON-fil.
    session_id skal være et anonymt løbenummer (fx 'test-01'), ALDRIG
    testpersonens navn - se note om anonymisering."""
    serializable_messages = []
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            content = [
                {"type": b.type, "text": getattr(b, "text", None), "input": getattr(b, "input", None)}
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
    print("Assistent: Hej! Lad os finde et forslag til dig. Hvilken sportsgren interesserer dig?")

    while True:
        user_input = input("Dig: ")
        messages.append({"role": "user", "content": user_input})

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
            print("Assistent:", " ".join(text_blocks))

        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block:
            afklaring = tool_use_block.input
            print("\n[Afklaring fuldført]:", json.dumps(afklaring, ensure_ascii=False, indent=2))
            save_transcript(session_id, messages, afklaring)
            return afklaring


if __name__ == "__main__":
    run_dialog()
