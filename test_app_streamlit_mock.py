"""
Automatiseret regressionstest af app.py's Streamlit-logik via Streamlit AppTest
(streamlit.testing.v1) - simulerer en session UDEN en rigtig browser og UDEN
rigtige Anthropic API-kald (klienten mockes, ligesom i test_validering_mock.py,
for at undgaa API-omkostning ved hver testkoersel).

VIGTIGT (laes foer du koerer denne): AppTest er IKKE afproevet af mig selv paa
din maskine - jeg kan ikke koere streamlit fra denne session (ingen
netvaerksadgang/venv i broen til din Mac). Der er en reel risiko for, at
scriptet fejler ved foerste koersel pga. en Streamlit-version-detalje, eller
en forkert antagelse om, hvordan AppTest haandterer et PROGRAMMATISK
st.rerun()-kald (til forskel fra et rerun udloest af en widget-interaktion).
Hvis det fejler: vis mig fejlbeskeden - saa retter vi TESTEN, ikke noedvendigvis
app.py, foer vi konkluderer noget om koden.

Daekker IKKE: faktisk visuel rendering (ikoner, spinner, layout) - det kraever
stadig en manuel `streamlit run app.py`-test i browseren.
"""
import sys
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest


def _ss_get(session_state, key, default=None):
    """AppTest's session_state understøtter ikke .get() som en almindelig
    dict - kun attribut-/indeksadgang, som rejser en fejl på et manglende
    nøgle. Denne helper giver den samme .get()-semantik som en dict."""
    try:
        return session_state[key]
    except (KeyError, AttributeError):
        return default

sys.path.insert(0, ".")


def _sdk_text_block(tekst):
    # Samme spec-praecisering som _sdk_tool_use_block, af samme grund.
    b = MagicMock(spec=["type", "text"])
    b.type = "text"
    b.text = tekst
    return b


def _sdk_tool_use_block(input_dict, block_id="toolu_test"):
    # BUG FUNDET 2026-09-01 (via brugerens live-koersel af denne test): en
    # ubegraenset MagicMock() auto-genererer ETHVERT attribut, du ikke selv
    # saetter - dvs. getattr(b, "text", None) returnerer en NY MagicMock, ikke
    # None, medmindre .text saettes eksplicit. Et rigtigt Anthropic SDK
    # tool_use-objekt har slet ikke et .text-attribut, saa getattr(..., None)
    # ville korrekt give None i produktion - den oprindelige mock simulerede
    # altsaa SDK-objektet forkert (for "generoest"), ikke omvendt. Rettet ved
    # at bruge spec=["type", "id", "input"], saa mock'en kun tillader de
    # attributter, et rigtigt tool_use-objekt faktisk har - adgang til .text
    # gaar nu korrekt til den almindelige getattr(..., None)-fallback.
    b = MagicMock(spec=["type", "id", "input"])
    b.type = "tool_use"
    b.id = block_id
    b.input = input_dict
    return b


def lav_response(content_blocks):
    r = MagicMock()
    r.content = content_blocks
    return r


def test_normal_dialog_uden_tool_use():
    """Almindelig brugerbesked -> Haiku svarer med ren tekst, ingen tool_use."""
    with patch("agents.orchestrator.client.messages.create") as mock_create:
        mock_create.return_value = lav_response([
            _sdk_text_block("Hvilket marked vil du gerne satse paa?")
        ])
        at = AppTest.from_file("app.py").run()
        assert not at.exception, f"Uventet exception ved opstart: {at.exception}"

        at.chat_input[0].set_value("Premier League").run()
        assert not at.exception, f"Uventet exception efter chat_input: {at.exception}"
        assert mock_create.called, "Modellen blev aldrig kaldt"
        print("OK: normal dialog uden tool_use virker, ingen exception")


def test_afvist_indsats_auto_fortsaetter():
    """Simulerer en afvist indsats (-50) efterfulgt af en gyldig (100) -
    tester BAADE valider_indsats()-integrationen OG at UI'et selv fortsaetter
    (afventer_tool_result-grenen), uden at scriptet selv skal 'klikke' igen."""
    kald_taeller = {"n": 0}

    def side_effect(*args, **kwargs):
        kald_taeller["n"] += 1
        beskeder = kwargs.get("messages", [])
        for i in range(1, len(beskeder)):
            assert beskeder[i]["role"] != beskeder[i - 1]["role"], (
                f"Rolle-alternering brudt ved kald {kald_taeller['n']}, "
                f"besked {i}: to '{beskeder[i]['role']}'-beskeder i traek"
            )
        if kald_taeller["n"] == 1:
            return lav_response([
                _sdk_tool_use_block({
                    "liga": "Serie A", "marked": "Over/Under 2.5", "indsats": -50
                })
            ])
        return lav_response([
            _sdk_tool_use_block({
                "liga": "Serie A", "marked": "Over/Under 2.5", "indsats": 100
            })
        ])

    with patch("agents.orchestrator.client.messages.create", side_effect=side_effect):
        at = AppTest.from_file("app.py").run()
        at.chat_input[0].set_value("Serie A, Over/Under 2.5, 50 kr negativ test").run()
        assert not at.exception, f"Uventet exception: {at.exception}"

        for _ in range(3):
            if _ss_get(at.session_state, "afklaring"):
                break
            at.run()

        assert _ss_get(at.session_state, "afklaring") is not None, (
            "afklaring blev ALDRIG sat - enten fejler auto-fortsaet-logikken, "
            "eller AppTest haandterer ikke det programmatiske st.rerun() som "
            "antaget. Vis mig denne fejl."
        )
        assert _ss_get(at.session_state, "afklaring")["indsats"] == 100
        assert kald_taeller["n"] >= 2, "Den ugyldige indsats udloeste aldrig et andet API-kald"
        print(f"OK: afvist indsats -> auto-fortsaet -> gyldig afklaring ({kald_taeller['n']} kald)")


def test_api_fejl_haandteres_ikke_crash():
    """Simulerer et API-udfald (fx netvaerksfejl) - appen maa IKKE crashe, og
    brugeren skal se en synlig fejlbesked (st.error).

    RETTET 2026-09-01: den oprindelige version af denne test tjekkede, at
    st.session_state.api_fejl STADIG var sat efter hele render-cyklussen -
    men app.py's design er bevidst at nulstille api_fejl EFTER den er vist
    (samme "flash message"-moenster som mange webapps bruger), saa en gammel
    fejl ikke vises igen og igen paa hver efterfoelgende rerun. Testen skal
    derfor tjekke, at fejlen FAKTISK blev vist via st.error() - ikke at den
    stadig ligger i session_state bagefter."""
    with patch("agents.orchestrator.client.messages.create", side_effect=Exception("Simuleret netvaerksfejl")):
        at = AppTest.from_file("app.py").run()
        at.chat_input[0].set_value("Bundesliga").run()
        assert not at.exception, (
            f"Appen crashede paa en simuleret API-fejl - fejlhaandteringen virker "
            f"IKKE: {at.exception}"
        )
        assert len(at.error) > 0, "Ingen synlig fejlbesked (st.error) blev vist efter simuleret API-udfald"
        assert "Simuleret netvaerksfejl" in at.error[0].value, (
            f"Fejlbeskeden indeholder ikke den forventede tekst: {at.error[0].value}"
        )
        print("OK: simuleret API-fejl haandteres uden crash, og en synlig fejlbesked vises")


def test_kredsloebsafbryder_stopper_uendelig_loekke():
    """Simulerer at Haiku BLIVER VED med at foreslaa en ugyldig indsats,
    session efter session - kredsloebsafbryderen (MAX_FEJL_FORSOEG = 3 i
    app.py) skal stoppe den automatiske gentagelse efter praecis 3 forsoeg,
    IKKE loebe i det uendelige, og i stedet vise en synlig fejlbesked og lade
    brugeren skrive selv igen.

    RETTET 2026-09-01 (efter brugerens foerste koersel): den oprindelige
    version antog, at hvert eksplicit at.run() svarer til AeT enkelt
    script-gennemloeb. Det viste sig forkert - AppTest kaeder faktisk de
    interne st.rerun()-kald automatisk igennem til en stabil tilstand inden
    for ÉT enkelt .run()-kald (kald_taeller ramte 3 allerede efter det foerste
    set_value().run()). Det er i sig selv et positivt fund: den indre
    "assert <= 5"-graense i side_effect blev IKKE udloest, hvilket beviser, at
    loekken faktisk stoppede ved 3 og ikke fortsatte i det uendelige."""
    kald_taeller = {"n": 0}

    def side_effect(*args, **kwargs):
        kald_taeller["n"] += 1
        assert kald_taeller["n"] <= 5, (
            "Kredsloebsafbryderen stoppede IKKE - mock blev kaldt mere end "
            "5 gange, hvilket peger paa en uendelig auto-rerun-loekke."
        )
        return lav_response([
            _sdk_tool_use_block({
                "liga": "La Liga", "marked": "Asian Handicap", "indsats": -1
            })
        ])

    with patch("agents.orchestrator.client.messages.create", side_effect=side_effect):
        at = AppTest.from_file("app.py").run()
        at.chat_input[0].set_value("La Liga, Asian Handicap, altid ugyldig indsats").run()
        assert not at.exception, f"Uventet exception: {at.exception}"

        assert kald_taeller["n"] == 3, (
            f"Forventede praecis 3 API-kald foer kredsloebsafbryderen stopper "
            f"den automatiske loop, fik {kald_taeller['n']}"
        )
        assert not _ss_get(at.session_state, "afventer_tool_result"), (
            "afventer_tool_result er stadig True - kredsloebsafbryderen "
            "stoppede ikke loopet"
        )
        assert _ss_get(at.session_state, "afklaring") is None, (
            "afklaring blev sat, selvom indsatsen ALDRIG blev gyldig - "
            "kredsloebsafbryderen boer stoppe UDEN at fuldfoere afklaringen"
        )
        assert len(at.error) > 0, "Ingen fejlbesked vist til brugeren, efter kredsloebsafbryderen udloeste"
        print(f"OK: kredsloebsafbryderen stopper efter praecis {kald_taeller['n']} forsoeg, viser fejlbesked, ingen uendelig loekke")


if __name__ == "__main__":
    test_normal_dialog_uden_tool_use()
    test_afvist_indsats_auto_fortsaetter()
    test_api_fejl_haandteres_ikke_crash()
    test_kredsloebsafbryder_stopper_uendelig_loekke()
    print("\nALLE TESTS BESTAAET (se stadig advarslen oeverst i filen om AppTest-usikkerhed)")
