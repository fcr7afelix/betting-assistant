"""
Streamlit-UI oven på samme dialoglogik som agents/orchestrator.py's run_dialog().

VIGTIGT: run_dialog() kan IKKE genbruges direkte her - den bruger input(), som
blokerer og ikke findes i en Streamlit-session (request/response-baseret, ikke
en løbende terminal-loop). I stedet genbruges de samme byggesten (SYSTEM_PROMPT,
AFKLARING_TOOL, client, tilfoej_ikoner, valider_indsats) fra orchestrator.py,
men samtale-tilstanden holdes i st.session_state. Al logik (retry, ikoner,
indsats-validering) er identisk med CLI-versionen - kun state-håndteringen er
anderledes: når en indsats afvises, fortsætter koden AUTOMATISK med et nyt
API-kald på næste genkørsel, uden at vente på ny brugerinput (Streamlits
st.chat_input triggede ellers kun på ny brugerinteraktion).

EFTER Orchestratorens dialog-lag har afklaret liga/marked/indsats, overtager
den deterministiske sekventering (Data -> Analyse -> Transparens ->
Vurdering) - ren Python-kontrolflow, INGEN LLM-beslutning om rækkefølgen
(jf. projektloggens LÅSTE "Rækkefølgestyring"-afsnit, bekræftet 2026-08-27).
Se _byg_forslag() nedenfor.

KORT-VISNING (tilføjet 2026-09-08, se projektloggens "Kort-styling"-fund):
bet assessment-kortet vises som native Streamlit-elementer via
_vis_bet_assessment(), IKKE som byg_bet_assessment()'s formaterede
tekstblok - den oprindelige ```-kodeblok wrappede ikke lange linjer og
lavede en sidelæns scroll, der gjorde indhold nemt at overse. Bruger
risikobilledet + bestem_grundlagskvalitet() DIREKTE. byg_bet_assessment()
forbliver den tekstbaserede reference (bruges af testscripts m.m.),
uaændret og ubrugt her.

INGEN anbefaling af et udfald vises noget sted i denne fil - se
Transparensagentens docstring/projektloggens "Bet Assessment-kort" for
hvorfor: der findes intet uafhængigt grundlag i arkitekturen for at pege
på et udfald som "anbefalet"; at gøre det ville reelt genindføre den
matematisk beviste cirkularitet fra degenerationsfundet 2026-09-02.
"""
import html
import streamlit as st
from dotenv import load_dotenv

from agents.orchestrator import (
    client,
    SYSTEM_PROMPT,
    AFKLARING_TOOL,
    tilfoej_ikoner,
    valider_indsats,
    GRAENSE_HOEJ_INDSATS,
    HOEJ_INDSATS_BESKED,
    save_transcript,
)
from agents.dataagent import (
    vaelg_kamp,
    rangér_kampe_med_odds,
    hent_kampe,
    hent_nyheder,
    rens_tekst,
    FALLBACK_BESKED,
    DataagentFejl,
    hent_team_id,
    hent_historisk_over_rate,
    _sidste_saeson_for_kickoff,
)
from agents.analyseagent import analyser_nyheder, AnalyseagentFejl
from agents.transparensagent import byg_risikobillede
from agents.vurderingsagent import bestem_grundlagskvalitet, bestem_value_signal

load_dotenv()

st.set_page_config(page_title="Betting Assistant", page_icon="🎲")
st.title("Betting Assistant")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "afklaring" not in st.session_state:
    st.session_state.afklaring = None
if "afventer_tool_result" not in st.session_state:
    st.session_state.afventer_tool_result = False
if "fejl_forsoeg" not in st.session_state:
    st.session_state.fejl_forsoeg = 0
if "api_fejl" not in st.session_state:
    st.session_state.api_fejl = None
if "risikobillede" not in st.session_state:
    st.session_state.risikobillede = None
if "forslag_besked" not in st.session_state:
    st.session_state.forslag_besked = None


MAX_FEJL_FORSOEG = 3  # kredsløbsafbryder: stop automatisk gentagelse hvis
# Haiku bliver ved med at kalde funktionen med en ugyldig indsats, i stedet
# for at risikere en uendelig auto-rerun-løkke uden brugerinvolvering.


GRUNDLAGSKVALITET_FARVER = {
    "Høj": "#22c55e",
    "Mellem": "#d97706",
    "Lav": "#ef4444",
}  # KORT-REDESIGN 2026-09-11 (se projektloggen "Kort-redesign"): erstatter
# den tidligere GRUNDLAGSKVALITET_VISNING (st.success/warning/error), som
# hver rendrede en STOR, farvet boks. I det haandbyggede HTML-kort deler
# Grundlagskvalitet, Value signal og udfaldsrækkerne IKKE laengere samme
# farvekanal (se _byg_value_signal_html()'s docstring for hvorfor det er
# en reel rettelse, ikke kun kosmetik) - kun selve niveau-ordet farves her,
# boksen omkring er ensartet neutral.

# REDESIGN 2026-09-11: kortet gik fra native Streamlit-widgets til ét
# haandbygget HTML/CSS-element. Udgangspunkt: et Figma Make-udkast (AI-
# genereret fra en prompt), derefter flere runder brugerkritik og -rettelse
# FOER denne kode blev skrevet - se _vis_bet_assessment()'s docstring for
# hvilke konkrete fejl der blev fundet og rettet undervejs (bl.a. et
# udfald der fejlagtigt blev farve-fremhaevet som en implicit anbefaling,
# og en dupliceret "Grundlagskvalitet"-label i Value Signal-boksen).
_KORT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
.vk-kort { font-family: 'Inter', sans-serif; max-width: 560px; background:#151720; border:1px solid #252836; border-radius:10px; overflow:hidden; color:#e2e4ed; margin-bottom: 8px; }
.vk-header { display:flex; align-items:center; background:#1a1d2b; border-bottom:1px solid #252836; padding:0 16px; min-height:38px; flex-wrap:wrap; }
.vk-header-liga { font-size:10px; font-weight:700; letter-spacing:.1em; color:#9ca3af; text-transform:uppercase; }
.vk-header-sep { width:1px; height:16px; background:#2e3246; margin:0 14px; }
.vk-header-marked { font-size:10px; font-weight:500; letter-spacing:.06em; color:#6b7280; text-transform:uppercase; }
.vk-header-spacer { flex:1; }
.vk-header-stake { font-size:10px; font-weight:500; color:rgb(255,244,0); letter-spacing:.04em; }
.vk-titel { padding:18px 16px 16px; border-left:3px solid #3b82f6; background:#151720; }
.vk-titel-tekst { padding-left:14px; font-size:20px; font-weight:700; line-height:1.2; letter-spacing:-0.01em; }
.vk-hold { color:#fff; }
.vk-vs { color:#4b5563; font-weight:500; font-size:16px; margin:0 10px; }
.vk-odds-blok { padding:0 16px 16px; }
.vk-odds-hint { font-size:9px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:#4b5563; margin:0 0 8px; line-height:1.4; }
.vk-odds-row { background:#1a1d2b; border:1px solid #252836; border-radius:8px; padding:12px 14px; display:flex; align-items:center; margin-bottom:4px; }
.vk-odds-label { font-size:14px; font-weight:500; color:#c9ccd6; flex:1; }
.vk-odds-tal { font-size:26px; font-weight:700; color:#fff; font-family:'JetBrains Mono',monospace; letter-spacing:-0.02em; margin-right:10px; }
.vk-odds-pct { padding:3px 8px; background:#252836; border:1px solid #2e3246; border-radius:4px; font-size:11px; font-weight:600; color:#9ca3af; font-family:'JetBrains Mono',monospace; }
.vk-boks { margin:0 16px 12px; border-radius:8px; padding:12px 14px; }
.vk-boks-neutral { background:rgb(39,35,57); border:1px solid rgb(67,74,97); }
.vk-boks-groen { background:#111a13; border:1px solid #1a3d1f; }
.vk-boks-head { display:flex; align-items:center; gap:8px; margin-bottom:6px; flex-wrap:wrap; }
.vk-boks-label { font-size:10px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:#9ca3af; }
.vk-boks-status { font-size:12px; font-weight:700; letter-spacing:.04em; }
.vk-boks-body { margin:0; font-size:12px; color:#6b7280; line-height:1.55; }
.vk-boks-body b { color:#9ca3af; font-family:'JetBrains Mono',monospace; font-weight:600; }
.vk-caption-linje { margin:0 16px 10px !important; font-size:12px; color:#6b7280; line-height:1.5; }
.vk-kontekst { margin:0 16px 16px; background:#1a1d2b; border:1px solid #252836; border-radius:8px; overflow:hidden; }
.vk-kontekst-head { display:flex; align-items:center; gap:10px; padding:11px 14px; border-bottom:1px solid #252836; flex-wrap:wrap; }
.vk-kontekst-badge { padding:2px 8px; background:#252836; border-radius:4px; font-size:10px; font-weight:600; color:#6b7280; }
.vk-kontekst-body { padding:12px 14px 14px; }
.vk-fund-row { display:flex; gap:10px; align-items:flex-start; margin-bottom:10px; }
.vk-fund-row:last-child { margin-bottom:0; }
.vk-fund-dash { font-size:12px; color:#4b5563; margin-top:2px; flex-shrink:0; font-family:'JetBrains Mono',monospace; }
.vk-fund-tekst { font-size:13px; color:#c9ccd6; line-height:1.55; }
.vk-usikker-label { font-size:10px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:#d97706; margin:14px 0 6px; }
.vk-usikker-tekst { margin:0; font-size:13px; color:#9ca3af; line-height:1.55; }
.vk-footer { padding:12px 16px 16px; border-top:1px solid #1e2130; }
.vk-pille-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.vk-pille { display:flex; align-items:center; background:#1a1d2b; border:1px solid #252836; border-radius:6px; overflow:hidden; height:30px; }
.vk-pille-label { padding:0 10px; font-size:9px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; color:#6b7280; background:#1e2130; height:100%; display:flex; align-items:center; border-right:1px solid #252836; }
.vk-pille-vaerdi { padding:0 10px; font-size:12px; font-weight:600; color:#e2e4ed; font-family:'JetBrains Mono',monospace; height:100%; display:flex; align-items:center; }
.vk-disclaimer { margin:8px 16px 0 !important; font-size:11px; color:#4b5563; line-height:1.5; }
</style>
"""


def _byg_pille_html(label, vaerdi):
    return (
        '<div class="vk-pille">'
        '<span class="vk-pille-label">%s</span>'
        '<span class="vk-pille-vaerdi">%s</span>'
        '</div>'
    ) % (html.escape(str(label)), html.escape(str(vaerdi)))


def _byg_odds_row_html(u):
    """Bygger EN udfaldsraekke. REDESIGN 2026-09-11: begge udfald har
    NOEJAGTIGT samme styling - ingen farve/kant fremhaever det ene udfald
    over det andet. Figma Make-udkastet fremhaevede oprindeligt "Over 2.5"
    med groen kant/tekst; det blev rettet FOER denne kode blev skrevet,
    fordi det reelt fungerede som en implicit anbefaling af ét udfald - i
    modstrid med kortets eget disclaimer og projektets laaste princip (se
    modul-docstringens "INGEN anbefaling af et udfald")."""
    return (
        '<div class="vk-odds-row">'
        '<span class="vk-odds-label">%s</span>'
        '<div style="display:flex;align-items:center;">'
        '<span class="vk-odds-tal">%s</span>'
        '<span class="vk-odds-pct">%s</span>'
        '</div></div>'
    ) % (
        html.escape(u["navn"]),
        html.escape(str(u["odds"])),
        html.escape(_formater_procent_visning(u["implicit_sandsynlighed"])),
    )


def _byg_grundlagskvalitet_html(grundlagskvalitet):
    farve = GRUNDLAGSKVALITET_FARVER.get(grundlagskvalitet, "#9ca3af")
    return (
        '<div class="vk-boks vk-boks-neutral">'
        '<div class="vk-boks-head">'
        '<span class="vk-boks-label">Grundlagskvalitet</span>'
        '<span class="vk-boks-status" style="color:%s;">%s</span>'
        '</div>'
        '<p class="vk-boks-body">Udtryk for m\u00e6ngden af relevant '
        'kontekst systemet fandt om kampen, IKKE en vurdering af '
        'sandsynligheden for at vinde.</p>'
        '</div>'
    ) % (farve, html.escape(grundlagskvalitet.upper()))


def _byg_kontekst_html(kontekst):
    fund = kontekst.get("fund", [])
    kilder_relevante = kontekst.get("kilder_vurderet_relevante", 0)
    kilder_i_alt = kontekst.get("kilder_i_alt", 0)
    usikkerhedspunkt = kontekst.get("usikkerhedspunkt")

    if fund:
        fund_html = "".join(
            '<div class="vk-fund-row"><span class="vk-fund-dash">\u2014</span>'
            '<span class="vk-fund-tekst">%s</span></div>' % html.escape(f)
            for f in fund
        )
    else:
        fund_html = (
            '<p class="vk-boks-body">Ingen relevante nyheder fundet for '
            'denne kamp.</p>'
        )

    usikker_tekst = (
        html.escape(usikkerhedspunkt) if usikkerhedspunkt
        else "Intet specifikt usikkerhedspunkt fundet i den tilg\u00e6ngelige kontekst."
    )

    return (
        '<div class="vk-kontekst">'
        '<div class="vk-kontekst-head">'
        '<span class="vk-boks-label">Kontekst</span>'
        '<span class="vk-kontekst-badge">%d af %d kilder</span>'
        '</div>'
        '<div class="vk-kontekst-body">%s'
        '<div class="vk-usikker-label">Hvad kunne \u00e6ndre dette?</div>'
        '<p class="vk-usikker-tekst">%s</p>'
        '</div></div>'
    ) % (kilder_relevante, kilder_i_alt, fund_html, usikker_tekst)

RESET_KNAP_LABEL = "🔁 Ny forespørgsel"


def _formater_procent_visning(vaerdi):
    if vaerdi is None:
        return "–"
    return f"{vaerdi * 100:.1f}%"


def _kald_model_og_haandter():
    """Kalder Anthropic API'et med den aktuelle samtalehistorik, håndterer et
    evt. tool_use-kald (validering + gemning), og sætter afventer_tool_result,
    hvis indsatsen blev afvist. Bruges BÅDE når en ny brugerbesked lige er
    tilføjet, OG når vi skal fortsætte automatisk efter en afvist indsats.

    Fejlhåndtering: et netværks-/API-kald kan fejle (timeout, rate limit,
    midlertidig serverfejl) - uden try/except ville det crashe hele appen med
    et råt Python-traceback midt i en usability-testsession. I stedet fanges
    fejlen og vises som en almindelig fejlbesked, og state efterlades i en
    tilstand brugeren selv kan komme videre fra (ny besked i chatten)."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[AFKLARING_TOOL],
            messages=st.session_state.messages,
        )
    except Exception as e:
        st.session_state.api_fejl = str(e)
        st.session_state.afventer_tool_result = False
        return

    st.session_state.messages.append({"role": "assistant", "content": response.content})

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block:
        afklaring = tool_use_block.input
        fejl = valider_indsats(afklaring.get("indsats"))
        if fejl:
            st.session_state.fejl_forsoeg += 1
            if st.session_state.fejl_forsoeg >= MAX_FEJL_FORSOEG:
                # Kredsløbsafbryder udløst: stop den automatiske løkke og lad
                # brugeren selv skrive næste besked i stedet.
                st.session_state.afventer_tool_result = False
                st.session_state.api_fejl = (
                    "Systemet kunne ikke opnå en gyldig indsats efter flere "
                    "forsøg. Skriv venligst dit ønskede beløb igen."
                )
                return
            st.session_state.messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": fejl,
                    "is_error": True,
                }],
            })
            st.session_state.afventer_tool_result = True
        else:
            st.session_state.fejl_forsoeg = 0
            st.session_state.afklaring = afklaring
            save_transcript("streamlit-dev", st.session_state.messages, afklaring)


def _byg_value_signal(liga, kamp, risikobillede):
    """Beriger risikobilledet med et VALUE SIGNAL for Over/Under 2.5 -
    tilfoejet 2026-09-09, se projektloggens 'Value signal - reversering
    af laast Transparensagent-design' for den fulde begrundelse og
    Trin A/Trin B-audit. Scope: KUN Over/Under 2.5-markedet (Asian
    Handicap faar intet value signal - en bevidst afgraensning for at
    holde omfanget nede, se projektloggen).

    Fejler ALDRIG synligt for brugeren: enhver DataagentFejl under
    historik-opslaget resulterer i status \"FEJL\" i stedet for et
    crash - samme fejlhaandteringsprincip som resten af _byg_forslag()."""
    try:
        hjemme_id = hent_team_id(liga, kamp["hjemmehold"])
        ude_id = hent_team_id(liga, kamp["udehold"])
        sidste_saeson = _sidste_saeson_for_kickoff(kamp["kickoff_utc"])
        rate_hjemme, n_hjemme, turnering_hjemme = (
            (None, 0, None) if hjemme_id is None else hent_historisk_over_rate(hjemme_id, sidste_saeson)
        )
        rate_ude, n_ude, turnering_ude = (
            (None, 0, None) if ude_id is None else hent_historisk_over_rate(ude_id, sidste_saeson)
        )
    except DataagentFejl:
        return {"status": "FEJL", "forskel_pp": None, "n_hjemme": 0, "n_ude": 0,
                "turnering_hjemme": None, "turnering_ude": None, "liga": liga}

    if rate_hjemme is None or rate_ude is None:
        return {"status": "INSUFFICIENT_DATA", "forskel_pp": None, "n_hjemme": n_hjemme, "n_ude": n_ude,
                "turnering_hjemme": turnering_hjemme, "turnering_ude": turnering_ude, "liga": liga}

    over_udfald = next((u for u in risikobillede["udfald"] if u["navn"].startswith("Over")), None)
    under_udfald = next((u for u in risikobillede["udfald"] if u["navn"].startswith("Under")), None)
    over_raa = over_udfald["implicit_sandsynlighed"] if over_udfald else None
    under_raa = under_udfald["implicit_sandsynlighed"] if under_udfald else None

    # DE-VIGGET SANDSYNLIGHED (tilfoejet 2026-09-15, Punkt 2, option A+D -
    # se projekt-ramme-betting-agent.md for Trin A/Trin B-audit). Raa
    # implicit sandsynlighed (1/odds) summerer til >100% for et
    # 2-udfaldsmarked (bookmaker-marginen) - at sammenligne en historisk
    # forekomst direkte mod dette raa tal inflaterer bagatellen, hvilket
    # systematisk goer POSITIVT sjaeldnere end det reelt boer vaere.
    # Normaliseringen fjerner marginen proportionalt paa begge udfald,
    # foer sammenligningen. Hvis Under-udfaldet af en eller anden grund
    # mangler (ikke observeret i praksis, men ikke logisk udelukket),
    # falder vi tilbage til den raa vaerdi frem for at crashe.
    if over_raa is not None and under_raa is not None and (over_raa + under_raa) > 0:
        implicit = over_raa / (over_raa + under_raa)
    else:
        implicit = over_raa

    status, forskel = bestem_value_signal(rate_hjemme, n_hjemme, rate_ude, n_ude, implicit)
    return {"status": status, "forskel_pp": forskel, "n_hjemme": n_hjemme, "n_ude": n_ude,
            "turnering_hjemme": turnering_hjemme, "turnering_ude": turnering_ude, "liga": liga}


def _byg_forslag_for_kamp(kamp, liga, marked):
    """Kører RESTEN af den deterministiske sekventering (Analyse ->
    Transparens -> Vurdering) for ÉT allerede-valgt kamp-dict - udtrukket
    af _byg_forslag() 2026-09-09 saa 'naeste kamp'-knappen (se
    projektloggens opfoelgning 'C - delt rangeringsfunktion') kan genbruge
    resten af kæden uden at gentage kamp-udvælgelsen. Ren Python-
    kontrolflow, INGEN LLM-beslutning om selve rækkefølgen (jf.
    projektloggens LÅSTE "Rækkefølgestyring"-afsnit).

    Sætter ENTEN st.session_state.risikobillede ELLER
    st.session_state.forslag_besked - aldrig begge. Ved fejl eller
    mangelfuld data stoppes kæden på det trin, den fejler, og brugeren
    informeres eksplicit i stedet for et råt traceback."""
    if kamp.get("odds") is None:
        st.session_state.forslag_besked = (
            f"Fandt {kamp['hjemmehold']} vs {kamp['udehold']}, men ingen odds "
            f"kunne matches for {marked}. Prøv evt. et andet marked eller en "
            f"anden liga."
        )
        return

    try:
        nyheder_raa = hent_nyheder(kamp["hjemmehold"], kamp["udehold"])
    except DataagentFejl as e:
        st.session_state.forslag_besked = f"Kunne ikke hente nyheder: {e}"
        return

    # rens_tekst() anvendes her (og KUN her i wiring-laget) på hver nyheds
    # "beskrivelse", før Analyseagenten ser den - jf. dataagent.py's egen
    # docstring: rens_tekst løser støj-problemet, IKKE relevans (det er
    # Analyseagentens ansvar, uændret).
    nyheder = [
        {**n, "beskrivelse": rens_tekst(n.get("beskrivelse"))}
        for n in nyheder_raa
    ]

    try:
        kontekst = analyser_nyheder(kamp["hjemmehold"], kamp["udehold"], nyheder)
    except AnalyseagentFejl as e:
        st.session_state.forslag_besked = f"Kunne ikke analysere nyheder: {e}"
        return

    risikobillede = byg_risikobillede(kamp, kontekst)
    if marked == "Over/Under 2.5":
        risikobillede["value_signal"] = _byg_value_signal(liga, kamp, risikobillede)
    st.session_state.risikobillede = risikobillede


def _byg_forslag(afklaring):
    """Kører den deterministiske sekventering (Data -> Analyse -> Transparens
    -> Vurdering) EFTER Orchestratorens dialog-lag har afklaret liga, marked
    og indsats - ren Python-kontrolflow, INGEN LLM-beslutning om selve
    rækkefølgen (jf. projektloggens LÅSTE "Rækkefølgestyring"-afsnit).

    Køres KUN ÉN gang pr. afklaring - resultatet caches i
    st.session_state.risikobillede/forslag_besked, fordi Streamlit genkører
    hele scriptet ved hver interaktion, og hverken Odds API-quota eller
    Haiku-credits skal bruges på at genberegne det samme forslag ved hver
    rerun.

    TILFØJET 2026-09-09 ('næste kamp'): henter nu HELE den rangerede
    kandidatliste via rangér_kampe_med_odds() (samme kriterium/rækkefølge
    som vaelg_kamp() - se dens docstring) og cacher den i
    st.session_state.kamp_kandidater/kamp_index, så en 'næste kamp'-knap
    kan skifte til kandidat nr. 2, 3 osv. uden at gen-hente kampe/odds.
    Er kandidatlisten tom (ingen kampe har odds), falder koden tilbage til
    vaelg_kamp()'s uændrede naermeste-kickoff-logik - der findes ingen
    rangering at tilbyde 'næste kamp' fra i det tilfælde, jf. projektloggen."""
    liga = afklaring["liga"]
    marked = afklaring["marked"]

    try:
        kandidater = rangér_kampe_med_odds(liga, marked)
        # Til empiri-loggen (se claude/empiri-log-10-kampe.md): "antal
        # kandidatkampe i 7-dages-vinduet" er IKKE samme tal som antal
        # kandidater MED odds - hent_kampe() er allerede cachet af
        # rangér_kampe_med_odds()'s interne kald, saa dette er IKKE et
        # ekstra netvaerkskald, kun et cache-opslag.
        st.session_state.antal_kampe_i_vindue = len(hent_kampe(liga, dage_frem=7))
        st.session_state.antal_kampe_med_odds = len(kandidater)
    except DataagentFejl as e:
        st.session_state.forslag_besked = f"Kunne ikke hente kampdata: {e}"
        return

    if kandidater:
        st.session_state.kamp_kandidater = kandidater
        st.session_state.kamp_index = 0
        _byg_forslag_for_kamp(kandidater[0], liga, marked)
        return

    # Ingen kandidater havde odds - fald tilbage til vaelg_kamp()'s
    # uændrede naermeste-kickoff-logik (fallback 2). Ingen rangering
    # cachet her, saa 'næste kamp'-knappen vises ikke i dette tilfælde.
    st.session_state.kamp_kandidater = None
    st.session_state.kamp_index = 0
    st.session_state.antal_kampe_med_odds = 0
    try:
        kamp = vaelg_kamp(liga, marked)
        st.session_state.antal_kampe_i_vindue = len(hent_kampe(liga, dage_frem=7))
    except DataagentFejl as e:
        st.session_state.forslag_besked = f"Kunne ikke hente kampdata: {e}"
        return

    if kamp == FALLBACK_BESKED:
        st.session_state.forslag_besked = kamp
        return

    _byg_forslag_for_kamp(kamp, liga, marked)



def _scroll_til_kort():
    """UX-BUGFIX (2026-09-11, fundet under empiri-log kamp 1 - se
    projektloggen): st.rerun() nulstiller browserens scroll-position til
    toppen af siden (Streamlit har ingen indbygget scroll-API til dette).
    For brugeren betyder det, at siden efter valg af liga/marked - og efter
    hvert naeste kamp-klik - springer tilbage til toppen, hvor assistent-
    dialogen startede, mens selve bet assessment-kortet vises langt nede.
    Det er misvisende (kan let laeses som at der ikke kom noget resultat)
    og risikerer at forurene de 5 planlagte usability-test-sessioner, som
    er en kerne-empirisk del af projektet - derfor prioriteret nu.
    Injicerer et lille JS-snippet der finder HTML-ankeret nedenfor inde i
    parent-dokumentet (components-iframen er isoleret fra selve siden) og
    scroller det i visning. Kaldes ved HVER rendering af kortet - baade
    foerste visning og efter naeste kamp - fordi begge veje gaar via
    st.rerun()."""
    st.markdown('<div id="bet-kort-start"></div>', unsafe_allow_html=True)
    st.components.v1.html(
        """
        <script>
        (function() {
            try {
                var doc = window.parent.document;
                var anker = doc.getElementById('bet-kort-start');
                if (anker) {
                    anker.scrollIntoView({behavior: 'smooth', block: 'start'});
                }
            } catch (e) {
                // Fejler stille - scroll er en UX-forbedring, ikke kritisk
                // funktionalitet; kortet er stadig tilgaengeligt ved manuel
                // scroll hvis dette af en eller anden grund ikke virker.
            }
        })();
        </script>
        """,
        height=0,
    )


def _vis_bet_assessment(risikobillede):
    """Viser bet assessment-kortet som ét håndbygget HTML/CSS-element
    (se modul-docstringen for arkitektur-baggrunden; se projektloggens
    "Kort-redesign 2026-09-11" for selve processen: udgangspunkt i et
    Figma Make-udkast (AI-genereret fra en prompt), efterfulgt af flere
    runder brugerkritik og -rettelse FØR denne kode blev skrevet. To
    konkrete fejl blev fundet og rettet undervejs: (1) "Over 2.5"-rækken
    var oprindeligt farve-fremhævet grøn, hvilket reelt fungerede som en
    implicit anbefaling af det udfald - i modstrid med kortets eget
    disclaimer og projektets låste princip om INGEN anbefaling; (2)
    Value Signal-boksens hoved viste fejlagtigt BÅDE "GRUNDLAGSKVALITET"
    og "VALUE SIGNAL" som label (en tydelig copy/paste-fejl fra AI-
    genereringen). Se GRUNDLAGSKVALITET_FARVER's og
    _byg_value_signal_html()'s docstrings for detaljerne.

    SIKKERHED: al tekst der stammer fra Analyseagentens LLM-fortolkning af
    skrabede nyheder (fund, usikkerhedspunkt) eller fra risikobilledets
    disclaimer-tekst escapes ALTID med html.escape() før indsættelse i
    HTML'en - kortet rendres nu via unsafe_allow_html=True, i modsætning
    til den tidligere widget-baserede version, hvor Streamlits markdown-
    rendering ikke udførte rå HTML/script som standard. Uden escaping
    kunne en skrabet nyhedstekst der tilfældigvis indeholder "<" eller et
    script-tag bryde layoutet eller udføre kode i brugerens browser -
    IKKE tidligere et problem, ER et problem nu.

    Renderer stadig DIREKTE fra risikobilledet + bestem_grundlagskvalitet();
    ingen tekst-parsing, ingen ny beregning, ingen anbefaling af ét
    udfald."""
    _scroll_til_kort()
    kontekst = risikobillede["kontekst"]
    afklaring = st.session_state.afklaring

    odds_html = "".join(_byg_odds_row_html(u) for u in risikobillede["udfald"])
    grundlagskvalitet = bestem_grundlagskvalitet(kontekst)

    value_signal = risikobillede.get("value_signal")
    value_signal_html = _byg_value_signal_html(value_signal) if value_signal else ""

    piller = []
    if risikobillede.get("kickoff_utc"):
        piller.append(_byg_pille_html("Kickoff UTC", risikobillede["kickoff_utc"]))
    piller.append(
        _byg_pille_html(
            "Bookmaker-margin",
            _formater_procent_visning(risikobillede["bookmaker_margin"]),
        )
    )
    piller_html = "".join(piller)

    kort_html = _KORT_CSS + (
        '<div class="vk-kort">'
        '<div class="vk-header">'
        '<span class="vk-header-liga">%s</span>'
        '<div class="vk-header-sep"></div>'
        '<span class="vk-header-marked">%s</span>'
        '<div class="vk-header-spacer"></div>'
        '<span class="vk-header-stake">%s kr.</span>'
        '</div>'
        '<div class="vk-titel"><div class="vk-titel-tekst">'
        '<span class="vk-hold">%s</span>'
        '<span class="vk-vs">vs</span>'
        '<span class="vk-hold">%s</span>'
        '</div></div>'
        '<div class="vk-odds-blok">'
        '<div class="vk-odds-hint">Odds og implicit sandsynlighed — '
        'rækkefølgen er en ren visningskonvention, IKKE en '
        'anbefaling af noget udfald</div>'
        '%s'
        '</div>'
        '%s'
        '%s'
        '%s'
        '<div class="vk-footer">'
        '<div class="vk-pille-row">%s</div>'
        '<p class="vk-caption-linje" style="margin:0 0 6px;">'
        'Bookmaker-margin = bookmakerens indbyggede fortjeneste — jo '
        'lavere, jo tættere er odds på den &quot;reelle&quot; '
        'sandsynlighed.</p>'
        '<p class="vk-disclaimer">%s</p>'
        '</div></div>'
    ) % (
        html.escape(afklaring["liga"]),
        html.escape(afklaring["marked"]),
        html.escape(str(afklaring["indsats"])),
        html.escape(risikobillede["hjemmehold"]),
        html.escape(risikobillede["udehold"]),
        odds_html,
        _byg_grundlagskvalitet_html(grundlagskvalitet),
        value_signal_html,
        _byg_kontekst_html(kontekst),
        piller_html,
        html.escape(risikobillede["disclaimer"]),
    )
    st.markdown(kort_html, unsafe_allow_html=True)


# BUGFIX 2026-09-14: football-data.org kalder IKKE altid en liga det
# samme, som appen viser brugeren. Bekraeftet empirisk (verify_liga_navne.py)
# mod /v4/competitions: PL/FL1/BL1/SA matcher deres egne visningsnavne 1:1,
# men PD (La Liga) hedder rent faktisk "Primera Division" i API'ets eget
# "name"-felt. Uden denne mapping sammenlignede _indeholder_liga() altid
# "La Liga" mod "Primera Division" og fandt ALDRIG et match - hvilket gav en
# FALSK positiv OBS-advarsel paa ethvert La Liga-kort, ogsaa naar holdets
# historik reelt VAR fra indevaerende La Liga-saeson (fundet paa kamp 3,
# Atletico Madrid vs Osasuna, se empiri-log-10-kampe.md). Kendt, accepteret
# vedligeholdelsesbyrde: hvis football-data.org omdoeber en anden
# konkurrence, opstaar samme type fejl ét andet sted, indtil den observeres
# og tilfoejes her manuelt - samme moenster som HOLDNAVN_ALIASSER.
LIGA_TIL_API_TURNERINGSNAVN = {
    "La Liga": "Primera Division",
}


def _formater_turnering_advarsel(liga, turnering_hjemme, turnering_ude):
    """TRANSPARENS-TILFOEJELSE (2026-09-09, opfoelgning paa oprykker-
    testen af Coventry/Hull/Ipswich - se dataagent.hent_historisk_over_rate()s
    docstring). Bygger en eksplicit advarselstekst, NAAR et holds historiske
    data stammer fra en anden turnering end den kampen selv spilles i (fx et
    nyoprykket holds Championship-data brugt i en Premier League-kamp), ELLER
    naar der slet INGEN historiske kampe blev fundet for et hold - returnerer
    None kun hvis begge hold har data, og den data er fra selve kampens liga.

    RETTET 2026-09-15 (fundet paa kamp 3, genkoersel 2: RC Celta de Vigo vs
    Real Racing Club de Santander, 0 kampe fundet for Racing Santander i
    season=2025). Den oprindelige version behandlede "turnering_label er
    None" (dvs. 0 kampe fundet, jf. hent_historisk_over_rate()s docstring)
    som "intet at advare om" via "if turnering_x and ...". Det er en
    fejlslutning: 0 kampe er IKKE det samme som "data bekraeftet fra egen
    liga" - det er "vi ved intet om dette holds baggrund", hvilket boer
    advares om, ikke tolkes som gruent lys. _byg_value_signal() haandterede
    allerede samme raadata-tilstand korrekt (blokerer value signal helt
    naar rate_hjemme/rate_ude er None) - denne funktion gjorde det modsatte.
    Se projekt-ramme-betting-agent.md for fuld begrundelse."""
    def _indeholder_liga(turnering_label):
        # turnering_label kan vaere en kommasepareret streng af flere
        # turneringer (jf. hent_historisk_over_rate()) - et hold hvis data
        # DELVIST er fra kampens egen liga (fx 'Premier League, FA Cup')
        # skal IKKE udloese advarslen, kun et hold hvor liga slet ikke
        # indgaar (fx rent 'Championship').
        api_navn = LIGA_TIL_API_TURNERINGSNAVN.get(liga, liga)
        return api_navn in [t.strip() for t in turnering_label.split(",")]

    afvigende = []
    if turnering_hjemme is None:
        afvigende.append("intet historisk datagrundlag fundet for hjemmeholdet")
    elif not _indeholder_liga(turnering_hjemme):
        afvigende.append(f"hjemmeholdets data er fra {turnering_hjemme}")
    if turnering_ude is None:
        afvigende.append("intet historisk datagrundlag fundet for udeholdet")
    elif not _indeholder_liga(turnering_ude):
        afvigende.append(f"udeholdets data er fra {turnering_ude}")
    if not afvigende:
        return None
    return ("OBS: " + "; ".join(afvigende)
            + f" (ikke bekraeftet {liga}) - typisk fordi holdet er op-/nedrykket, "
              "eller fordi holdet ikke daekkes af datakilden.")


def _byg_value_signal_html(value_signal):
    """Bygger Value Signal-blokken som HTML. Eksplicit ordvalg bevaret fra
    den oprindelige _vis_value_signal(): "historisk forekomst", ALDRIG
    "sandsynlighed" eller "model" - se vurderingsagent.bestem_value_signal()s
    docstring for hvorfor den sondring er faglig, ikke kosmetisk.

    KORT-REDESIGN 2026-09-11, to rettelser ift. Figma Make-udkastet:
    1) Udkastets bokshoved viste FEJLAGTIGT både "GRUNDLAGSKVALITET" og
       "VALUE SIGNAL" som label (en copy/paste-fejl fra AI-genereringen,
       genskabt fra den forudgående Grundlagskvalitet-blok) - rettet til
       kun at vise "VALUE SIGNAL".
    2) Kun POSITIVT-status blev OPRINDELIGT vist som en fyldt, farvet boks,
       mens FEJL/INSUFFICIENT_DATA/"ingen" blev vist som bære
       ".vk-caption-linje"-tekstlinjer UDEN omsluttende boks (bevidst
       informations-hierarki-valg: kun det faktisk bemærkelsesværdige
       fund skulle have visuel vægt). Denne asymmetri blev ALDRIG vist
       som en separat, godkendt mockup-iteration - kun POSITIVT-boksen er
       reelt blevet screenshottet og godkendt. Bruger flagede det som en
       visningsafvigelse fra det godkendte design (kortet virkede
       "ustylet" for "ingen"-status), efter en grundig eliminationstest
       (proces-genstart, cache-ryd, ny browser, ny liga - alle udelukket
       som forklaring) bekræftede at det IKKE var en cache-/miljofejl,
       men den faktiske, bevidste kode-adfærd.

    RETTET 2026-09-11 (brugerens eksplicitte beslutning, efter kritik af
    tre konkrete ulemper ved at boksificere alt: (1) INGEN er den
    hyppigste status i praksis og ville øge kortets højde for
    normaltilfældet, (2) risiko for at en neutral boks visuelt
    konkurrerer med POSITIVT-boksen og svaekker det låste ét-signal-
    princip, (3) revisionsstrategien er låst før de 5 usability-
    sessioner): ALLE fire statusser (FEJL, INSUFFICIENT_DATA, "ingen",
    POSITIVT) bruger nu SAMME boks-sprog som Grundlagskvalitet
    (.vk-boks .vk-boks-neutral med .vk-boks-head/.vk-boks-label/
    .vk-boks-status + .vk-boks-body) - kun færven på status-ordet og
    boksens baggrund (neutral vs. grøn) adskiller POSITIVT fra de
    øvrige. Risikoen fra punkt (2) ovenfor er derfor bevidst accepteret
    - konsistent boks-sprog på tværs af kortets to statusfelter blev
    af brugeren vurderet vigtigere end den marginale højde-/vægt-
    besparelse ved bare tekstlinjer.

    Tilføjet 2026-09-11 (brugerens godkendte tekstrettelse): en
    eksplicit sætning der understreger at signalet gælder Over 2.5
    SPECIFIKT og ikke er en anbefaling af dette udfald frem for Under
    2.5 - adresserer at boksens PLACERING (lige under Over 2.5-rækken)
    ellers kunne læses som et resterende, svagere anbefalings-signal
    via nærhed alene, selv efter farve-fremhævelsen af selve
    udfaldsrækken blev fjernet."""
    status = value_signal["status"]
    turnering_advarsel = _formater_turnering_advarsel(
        value_signal.get("liga"),
        value_signal.get("turnering_hjemme"),
        value_signal.get("turnering_ude"),
    )

    def _neutral_boks(status_tekst, body_html, farve="#9ca3af"):
        ud = (
            '<div class="vk-boks vk-boks-neutral">'
            '<div class="vk-boks-head">'
            '<span class="vk-boks-label">Value signal</span>'
            '<span class="vk-boks-status" style="color:%s;">%s</span>'
            '</div>'
            '<p class="vk-boks-body">%s</p>'
            '</div>'
        ) % (farve, html.escape(status_tekst), body_html)
        if turnering_advarsel:
            ud += (
                '<p class="vk-caption-linje" style="color:#d97706;">%s</p>'
                % html.escape(turnering_advarsel)
            )
        return ud

    if status == "FEJL":
        return _neutral_boks(
            "FEJL",
            "Kunne ikke hentes (fejl i historik-opslag).",
        )

    if status == "INSUFFICIENT_DATA":
        tekst = (
            f"Utilstrækkeligt historisk datagrundlag "
            f"({value_signal['n_hjemme']}+{value_signal['n_ude']} kampe fundet)."
        )
        return _neutral_boks(
            "UTILSTRÆKKELIGT DATAGRUNDLAG",
            html.escape(tekst),
        )

    forskel_pp = value_signal["forskel_pp"] * 100

    if status == "UBENYTTET":
        tekst = (
            f"Historisk forekomst afviger markant fra markedets pris "
            f"({forskel_pp:+.1f} procentpoint, baseret på "
            f"{value_signal['n_hjemme']}+{value_signal['n_ude']} historiske kampe). "
            f"Afvigelsen peger modsat af det, systemet er designet til at "
            f"vurdere (kun Over 2.5 tjekkes for et positivt signal) — "
            f"IKKE en anbefaling af Under 2.5."
        )
        return _neutral_boks("UBENYTTET", html.escape(tekst), farve="#d97706")

    if status != "POSITIVT":
        tekst = (
            f"Ingen ({forskel_pp:+.1f} procentpoint ift. markedets "
            f"implicitte sandsynlighed, baseret på "
            f"{value_signal['n_hjemme']}+{value_signal['n_ude']} historiske kampe)."
        )
        return _neutral_boks("INGEN", html.escape(tekst))

    boks = (
        '<div class="vk-boks vk-boks-groen">'
        '<div class="vk-boks-head">'
        '<span class="vk-boks-label">Value signal</span>'
        '<span class="vk-boks-status" style="color:#22c55e;">POSITIVT</span>'
        '</div>'
        '<p class="vk-boks-body">+%.1f procentpoint over markedets implicitte '
        'sandsynlighed for Over 2.5, baseret på <b>%s+%s</b> historiske '
        'kampe fra sidste sæson. Historisk forekomst er IKKE det samme '
        'som fremtidig sandsynlighed. Gælder Over 2.5 specifikt — '
        'IKKE en anbefaling af dette udfald frem for Under 2.5.</p>'
        '</div>'
    ) % (forskel_pp, value_signal["n_hjemme"], value_signal["n_ude"])
    if turnering_advarsel:
        boks += (
            '<p class="vk-caption-linje" style="color:#d97706;">%s</p>'
            % html.escape(turnering_advarsel)
        )
    return boks
def _nulstil_session():
    """Nulstiller HELE samtale- og forslagstilstanden, så brugeren kan
    starte en ny dialog forfra - tilføjet 2026-09-08 efter brugerens fund:
    uden denne var der ingen vej tilbage til chatten, når først et forslag
    var vist (kendt begrænsning, også i den oprindelige app.py, men mere
    alvorlig nu hvor der faktisk står et færdigt kort)."""
    st.session_state.messages = []
    st.session_state.afklaring = None
    st.session_state.afventer_tool_result = False
    st.session_state.fejl_forsoeg = 0
    st.session_state.api_fejl = None
    st.session_state.risikobillede = None
    st.session_state.forslag_besked = None
    st.session_state.kamp_kandidater = None
    st.session_state.kamp_index = 0
    st.session_state.antal_kampe_i_vindue = None
    st.session_state.antal_kampe_med_odds = None


# Vis hele samtalehistorikken (kun tekst-bidder, ikke rå tool-blokke)
for m in st.session_state.messages:
    content = m["content"]
    if isinstance(content, str):
        with st.chat_message(m["role"]):
            st.markdown(tilfoej_ikoner(content) if m["role"] == "assistant" else content)
    elif isinstance(content, list):
        for blok in content:
            tekst = getattr(blok, "text", None)
            if tekst:
                with st.chat_message(m["role"]):
                    st.markdown(tilfoej_ikoner(tekst))

if st.session_state.afklaring:
    st.success(
        f"Afklaring fuldført: {st.session_state.afklaring['liga']}, "
        f"{st.session_state.afklaring['marked']}, "
        f"{st.session_state.afklaring['indsats']} kr."
    )
    if st.session_state.afklaring["indsats"] > GRAENSE_HOEJ_INDSATS:
        st.warning(HOEJ_INDSATS_BESKED)

    if st.session_state.risikobillede is None and st.session_state.forslag_besked is None:
        # Første gang afklaringen vises - kør den deterministiske kæde ÉN
        # gang og cache resultatet, jf. _byg_forslag()'s docstring.
        with st.spinner("Finder det bedste forslag..."):
            _byg_forslag(st.session_state.afklaring)
        st.rerun()
    elif st.session_state.risikobillede:
        _vis_bet_assessment(st.session_state.risikobillede)
    elif st.session_state.forslag_besked:
        st.info(st.session_state.forslag_besked)

    # Til empiri-loggen (claude/empiri-log-10-kampe.md) - to ADSKILTE tal,
    # IKKE ét: "antal kampe i vinduet" (alle, uanset odds) vs. "antal MED
    # odds" (dem der reelt indgaar i rangeringen/kandidatlisten).
    antal_i_vindue = st.session_state.get("antal_kampe_i_vindue")
    antal_med_odds = st.session_state.get("antal_kampe_med_odds")
    if antal_i_vindue is not None:
        st.caption(
            f"Kandidatkampe i 7-dages-vinduet: {antal_i_vindue} i alt, "
            f"{antal_med_odds} med odds."
        )

    kandidater = st.session_state.get("kamp_kandidater")
    if st.session_state.risikobillede is not None and kandidater:
        naeste_index = st.session_state.get("kamp_index", 0) + 1
        if naeste_index < len(kandidater):
            # Bevidst NEUTRAL formulering - "laveste margin", IKKE "anbefalet"
            # eller "bedste" - se app.py's modul-docstring om hvorfor ordet
            # "anbefaling" er undgaaet alle steder i denne fil.
            naeste_label = f"Vis kamp nr. {naeste_index + 1} (næstlaveste bookmaker-margin)"
            if st.button(naeste_label):
                st.session_state.kamp_index = naeste_index
                st.session_state.risikobillede = None
                st.session_state.forslag_besked = None
                with st.spinner("Finder næste kamp..."):
                    _byg_forslag_for_kamp(
                        kandidater[naeste_index],
                        st.session_state.afklaring["liga"],
                        st.session_state.afklaring["marked"],
                    )
                st.rerun()
        else:
            st.caption("Ingen flere kampe med odds at vise for denne liga/marked.")

    if st.session_state.risikobillede is not None or st.session_state.forslag_besked is not None:
        if st.button(RESET_KNAP_LABEL):
            _nulstil_session()
            st.rerun()

elif st.session_state.afventer_tool_result:
    # Fortsæt AUTOMATISK - Haiku skal svare på fejlen, ikke vente på brugeren
    st.session_state.afventer_tool_result = False
    with st.spinner("Venter på svar..."):
        _kald_model_og_haandter()
    st.rerun()

else:
    if st.session_state.api_fejl:
        st.error(f"Der opstod en fejl: {st.session_state.api_fejl}")
        st.session_state.api_fejl = None

    if not st.session_state.messages:
        st.chat_message("assistant").markdown(
            tilfoej_ikoner(
                "Hej! Lad os finde et forslag til dig. Hvilken liga interesserer "
                "dig? (Premier League, Serie A, La Liga, Bundesliga eller Ligue 1)"
            )
        )

    bruger_input = st.chat_input("Skriv dit svar her...")
    if bruger_input:
        st.session_state.messages.append({"role": "user", "content": bruger_input})
        with st.spinner("Venter på svar..."):
            _kald_model_og_haandter()
        st.rerun()
