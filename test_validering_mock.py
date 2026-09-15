"""
Isoleret test af valideringsloopet i agents/orchestrator.py, UDEN at afhænge
af om Haiku selv vælger at kalde funktionen med et ugyldigt beløb (den fangede
det selv i den seneste live-test, så den relevante kodesti blev aldrig ramt).

Simulerer Anthropic-kaldet direkte, og tjekker desuden selv, at der ALDRIG
sendes to på hinanden følgende beskeder med samme rolle ("user"/"user") til
API'et - det var netop den fejl, den seneste rettelse skulle løse.
"""
import agents.orchestrator as orch

kald_tal = {"n": 0}


class FakeBlock:
    def __init__(self, type_, text=None, input_=None, id_=None):
        self.type = type_
        self.text = text
        self.input = input_
        self.id = id_


class FakeResponse:
    def __init__(self, content):
        self.content = content


def fake_create(**kwargs):
    kald_tal["n"] += 1
    n = kald_tal["n"]

    msgs = kwargs["messages"]
    for i in range(1, len(msgs)):
        forrige_rolle = msgs[i - 1]["role"]
        naeste_rolle = msgs[i]["role"]
        assert forrige_rolle != naeste_rolle, (
            f"FEJL: to '{forrige_rolle}'-beskeder i træk ved indeks {i-1}->{i} "
            f"- API'et ville have afvist dette!"
        )

    print(f"  [mock-kald #{n}] {len(msgs)} beskeder i historik, roller: "
          f"{[m['role'] for m in msgs]}")

    if n == 1:
        # Model "kalder" funktionen direkte med et ugyldigt beløb (-50)
        return FakeResponse([
            FakeBlock("tool_use", input_={
                "liga": "Serie A", "marked": "Asian Handicap", "indsats": -50
            }, id_="tool_1"),
        ])
    elif n == 2:
        # Modellen skal her modtage tool_result-fejlen og svare med almindelig
        # tekst (ikke et nyt tool_use) - simulerer at den beder om et nyt beløb
        return FakeResponse([
            FakeBlock("text", text="Beklager, indsatsen skal være positiv. Hvor meget vil du satse?"),
        ])
    elif n == 3:
        # Bruger har nu givet et gyldigt beløb - model kalder funktionen korrekt
        return FakeResponse([
            FakeBlock("tool_use", input_={
                "liga": "Serie A", "marked": "Asian Handicap", "indsats": 100
            }, id_="tool_2"),
        ])
    raise AssertionError(f"Uventet ekstra kald #{n}")


brugerinput = iter(["ignoreres (kaldes ved iteration 1)", "100"])


def fake_input(prompt):
    svar = next(brugerinput)
    print(f"  [simuleret input] {prompt}{svar}")
    return svar


orch.client.messages.create = fake_create
orch.input = fake_input

resultat = orch.run_dialog(session_id="mock-validering")

assert resultat == {"liga": "Serie A", "marked": "Asian Handicap", "indsats": 100}, resultat
assert kald_tal["n"] == 3, f"Forventede præcis 3 API-kald, fik {kald_tal['n']}"

print("\nALLE TJEK BESTÅET:")
print("- Ingen to ens roller i træk sendt til API'et (dobbelt-user-bug er rettet)")
print("- Ugyldig indsats (-50) blev afvist uden at afslutte dialogen")
print("- Gyldig indsats (100) blev til sidst accepteret korrekt")
