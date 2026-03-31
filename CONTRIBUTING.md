# Contributing

## Ziel

Dieses Projekt soll fuer Nicht-Programmierer nachvollziehbar bleiben. Bitte bevorzuge daher kleine, gut erklaerte Aenderungen statt grosser Umbauten.

Bevor du mitarbeitest, lies bitte auch:

- `CODE_OF_CONDUCT.md` fuer den erwarteten Umgangston
- `SECURITY.md` fuer sensible Meldungen
- das Pull-Request-Template unter `.github/PULL_REQUEST_TEMPLATE.md`

## Entwicklungsablauf

1. Aenderung klein halten und Verhalten nicht unnötig mit Refactorings vermischen.
2. Vor externen Zugriffeingriffen immer Validierung und klare Fehlermeldungen mitliefern.
3. Kommentare sollen Absicht und Debugging-Hinweise erklaeren.
4. Bei neuer Kernlogik immer Tests fuer Happy Path und Fehlerfall ergaenzen.
5. Bei nutzerrelevanten Änderungen README und CHANGELOG mitpflegen.
6. Neue Sensoren oder Services immer mit sinnvollen Debug-Hinweisen dokumentieren.

## Lokales Setup

```bash
python3 -m compileall custom_components tests
```

## Tests

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Optional:

```bash
pytest -q
python3 -m compileall custom_components tests
```

## Stil

- Kleine Funktionen mit einer klaren Aufgabe.
- Keine still geschluckten Exceptions.
- Log-Meldungen sollen sagen, was passiert ist und was man als Naechstes pruefen sollte.
- ASCII bevorzugen, damit Dateien in moeglichst vielen Umgebungen sauber bleiben.
- Pull Requests sollten kurz erklaeren, was sich fuer Nutzer veraendert und wie die Aenderung getestet wurde.
