"""
Vurderingsagenten (OMDOEBT 2026-09-08 fra "Beslutningsagent", se
projektloggen: "Agent-omdoebning" og "Bet Assessment-kort"): udfylder det
laaste bet assessment-kort ud fra Transparensagentens risikobillede, og
tilfoejer en Lav/Mellem/Hoej-kategorisering af GRUNDLAGSKVALITETEN (se
projektloggens "Vurderingsagentens Lav/Mellem/Hoej-kategorisering" for den
fulde begrundelse).

100% DETERMINISTISK - INGEN LLM-kald i denne fil. Dette besvarer det
tidligere aabne spoergsmaal i arkitekturdiagrammet ("Beslutningsagentens
type ikke laast"): selve kort-formateringen OG kategoriseringen er
kodestyret; kun de tekstuelle "fund" INDE I kortet stammer fra
Analyseagentens LLM-fortolkning, og de er allerede viderestillet uaendret
hele vejen igennem - Vurderingsagenten fortolker eller omformulerer dem
ikke.

Formatet er BEVIDST forskelligt fra det oprindeligt foreslaaede eksempel:
INGEN "Model probability", INGEN "Estimated edge", INGEN afsluttende
vaerdidom ("VALUE FOUND" el. lign.) - se projektloggens "Bet Assessment-
kort"-sektion for den fulde begrundelse.

KATEGORISERINGEN (Lav/Mellem/Hoej) er BEVIDST IKKE bygget paa
bookmaker_margin: margin er per konstruktion (naesten) altid minimum af
dagens kandidatpulje, fordi Dataagentens vaelg_kamp() allerede har valgt
den kamp med laveste margin - en terskel paa den vaerdi ville klumpe sig i
samme kategori for stort set alle kampe. Kategorien bygger i stedet
UDELUKKENDE paa Analyseagentens allerede byggede, empirisk BEKRAEFTEDE
varierende output (Firecrawl-valideringen viste 0-2 brugbare resultater ud
af 5 pr. kamp - reel per-kamp-variation, testet, ikke antaget). Den maaler
GRUNDLAGETS KVALITET (hvor meget relevant kontekst blev fundet) - IKKE en
sandsynlighed for at vinde. Det skal fremgaa eksplicit af teksten og
testes i usability-sessionerne, ikke antages forstaaet.
"""


def _formater_procent(vaerdi):
    if vaerdi is None:
        return "–"
    return f"{vaerdi * 100:.1f}%"


def _formater_odds_linje(u):
    return f"  {u['navn']}: {u['odds']} ({_formater_procent(u['implicit_sandsynlighed'])})"


def bestem_grundlagskvalitet(kontekst):
    """Kategoriserer UDELUKKENDE graden af relevant kontekst, Analyseagenten
    fandt - IKKE sandsynligheden for at vinde. Se modul-docstringen for
    hvorfor bookmaker_margin bevidst er udeladt fra denne beregning.

    Regel (REVIDERET 2026-09-08 efter EMPIRISK TEST paa de 10 rigtige
    testkampe - se projektloggen "De 10 empiriske testkampe", punkt 1):
    den oprindelige regel kraevede OGSAA at usikkerhedspunkt var fravaerende
    for "Hoej" - det viste sig i praksis UOPNAAELIGT, fordi reel
    skadesnyhed naesten pr. definition indeholder en vis usikkerhed (selv
    kampen med FLEST relevante kilder i testudtraekket, 4/5, havde et
    usikkerhedspunkt og landede fejlagtigt paa "Mellem"). Kategorien maaler
    derfor nu UDELUKKENDE antallet af relevante kilder; usikkerhedspunktet
    forbliver synligt som sin egen linje i kortet (se byg_bet_assessment()),
    uafhaengigt af kategorien - ikke fjernet, blot ikke laengere en
    kategori-gate.
    - "Høj": >=2 kilder vurderet relevante.
    - "Mellem": 1 kilde vurderet relevant.
    - "Lav": 0 kilder vurderet relevante.
    """
    kilder_relevante = kontekst.get("kilder_vurderet_relevante", 0)
    if kilder_relevante >= 2:
        return "Høj"
    if kilder_relevante == 0:
        return "Lav"
    return "Mellem"


MIN_KOMBINERET_DATAGRUNDLAG = 10  # min. antal historiske kampe (hjemme+ude
# kombineret), foer et value signal overhovedet vises - under denne graense
# er standardfejlen for stor til at et differencetal er meningsfuldt.
VAERDI_SIGNAL_TAERSKEL = 0.10  # 10 procentpoint, jf. brugerens forslag 2026-09-09


def bestem_value_signal(historisk_forekomst_hjemme, n_hjemme, historisk_forekomst_ude, n_ude, implicit_sandsynlighed):
    """VALUE SIGNAL (tilfoejet 2026-09-09, se projektloggens 'Value signal -
    reversering af laast Transparensagent-design' for den fulde
    begrundelse og Trin B-audit). Deterministisk, LLM-fri sammenligning af
    HISTORISK Over 2.5-forekomst (Dataagentens hent_historisk_over_rate(),
    sidste saeson, alle turneringer) mod markedets implicitte
    sandsynlighed for samme udfald.

    VIGTIGT: dette er IKKE en sandsynlighedsmodel og paastaar IKKE at
    kende 'den sande' sandsynlighed - kun at en observeret historisk
    frekvens ligger et stykke over/under markedets prissaetning. Historisk
    forekomst er ikke en garanti for fremtidig sandsynlighed - det SKAL
    fremgaa eksplicit i kortets tekst (se _vis_value_signal()
    i app.py), ikke kun i denne docstring.

    Returnerer et tuple (status, forskel_pp):
    - ("INSUFFICIENT_DATA", None): for lidt historisk datagrundlag
      (under MIN_KOMBINERET_DATAGRUNDLAG kampe i alt), eller intet odds
      at sammenligne med.
    - ("POSITIVT", forskel): historisk forekomst overstiger markedets
      implicitte sandsynlighed med mindst VAERDI_SIGNAL_TAERSKEL.
    - ("UBENYTTET", forskel): markedets implicitte sandsynlighed
      overstiger historisk forekomst med mindst VAERDI_SIGNAL_TAERSKEL -
      en reel, stor afvigelse findes, men i den retning, systemet ikke
      er designet til at handle paa (tilfoejet 2026-09-15, jf. kamp 7-
      fundet i empiri-loggen).
    - ("INGEN", forskel): forskellen er reelt ubetydelig (under
      taersklen i begge retninger)."""
    if implicit_sandsynlighed is None or (n_hjemme + n_ude) < MIN_KOMBINERET_DATAGRUNDLAG:
        return "INSUFFICIENT_DATA", None

    historisk_forekomst = (historisk_forekomst_hjemme + historisk_forekomst_ude) / 2
    forskel = historisk_forekomst - implicit_sandsynlighed

    if forskel >= VAERDI_SIGNAL_TAERSKEL:
        return "POSITIVT", forskel
    if forskel <= -VAERDI_SIGNAL_TAERSKEL:
        return "UBENYTTET", forskel
    return "INGEN", forskel


def byg_bet_assessment(risikobillede):
    """Formaterer risikobilledet til det endelige, brugervendte bet
    assessment-kort som tekst. Ren skabelon-udfyldning for oddsdata - ingen
    ny data, ingen ny vurdering af selve udfaldet, ingen LLM-formulering.
    Tilfoejer kun kategoriseringen af grundlagskvalitet (se
    bestem_grundlagskvalitet()) som ny, kodestyret information."""
    kontekst = risikobillede["kontekst"]

    linjer = []
    linjer.append(f"{risikobillede['hjemmehold']} vs {risikobillede['udehold']}")
    if risikobillede.get("kickoff_utc"):
        linjer.append(f"Kickoff (UTC): {risikobillede['kickoff_utc']}")
    linjer.append("")
    linjer.append(f"Bookmaker-margin: {_formater_procent(risikobillede['bookmaker_margin'])}")
    linjer.append("")
    linjer.append("Odds og implicit sandsynlighed (af bookmakerens odds):")
    for u in risikobillede["udfald"]:
        linjer.append(_formater_odds_linje(u))
    linjer.append("")

    fund = kontekst.get("fund", [])
    kilder_relevante = kontekst.get("kilder_vurderet_relevante", 0)
    kilder_i_alt = kontekst.get("kilder_i_alt", 0)
    linjer.append(f"Kontekst ({kilder_relevante} af {kilder_i_alt} kilder vurderet relevante):")
    if fund:
        for i, f in enumerate(fund, start=1):
            linjer.append(f"  {i}. {f}")
    else:
        linjer.append("  Ingen relevante nyheder fundet for denne kamp.")
    linjer.append("")

    usikkerhedspunkt = kontekst.get("usikkerhedspunkt")
    linjer.append("Hvad kunne ændre dette?")
    linjer.append(f"  {usikkerhedspunkt if usikkerhedspunkt else 'Intet specifikt usikkerhedspunkt fundet i den tilgængelige kontekst.'}")
    linjer.append("")

    grundlagskvalitet = bestem_grundlagskvalitet(kontekst)
    linjer.append(f"Grundlagskvalitet: {grundlagskvalitet}")
    linjer.append("  (Udtryk for mængden af relevant kontekst systemet fandt om kampen — IKKE en vurdering af sandsynligheden for at vinde.)")
    linjer.append("")

    linjer.append(risikobillede["disclaimer"])

    return "\n".join(linjer)
