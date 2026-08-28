# Udviklingsobservationer (IKKE usability-testdata)

Denne fil er dev-tidsobservationer fra egen test af Orchestratorens dialog-prompt,
FØR de fem formelle usability-sessioner. Ikke en kilde til Analyse-afsnittets
Habermas-/Lean Startup-empiri i sig selv, men dokumentation for at bestemte
fejltyper er systematiske, ikke tilfældige, når den senere, samlede promptrevision
skal begrundes.

## 2026-08-28
- Dialog-agenten (claude-haiku-4-5) brugte "laget" i stedet for korrekt dansk
  "holdet" i en tidligere test.
- Dialog-agenten brugte "toppfotballsmesterskab" (norsk/svensk-farvet) i stedet
  for korrekt dansk "topfodboldmesterskab" — session_id="dev", test af liga-feltet
  efter opdatering fra "sportsgren" til "liga".
- Mønster: to uafhængige instanser af norsk/svensk-farvet ordvalg på tværs af to
  forskellige dev-tests. Peger på en systematisk sprogkonsistens-svaghed i
  claude-haiku-4-5's danske output, ikke en enkeltstående fejl.
