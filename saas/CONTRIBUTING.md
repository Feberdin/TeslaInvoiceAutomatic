# Contributing

## Zweck

Diese Datei beschreibt, wie Änderungen in diesem MVP nachvollziehbar und sicher eingebracht werden.

## Workflow

1. Kleine, getrennte Änderungen bevorzugen.
2. Vor größeren Umbauten zuerst Tests oder Sicherheitsnetz ergänzen.
3. Änderungen mit verständlichen Kommentaren und klaren Fehlermeldungen schreiben.
4. Vor einem Commit mindestens die Kernlogik-Tests laufen lassen.

## Lokale Entwicklung

### App starten

```bash
cp .env.example .env
docker compose up --build
```

### Tests ausführen

```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests
```

## Code-Stil

- Python: kleine Funktionen, klare Namen, defensive Fehlerbehandlung
- Frontend: klare Labels, verständliche Statusmeldungen, keine versteckte Magie
- Logs: keine sensiblen Daten ausschreiben

## Pull-Request-Check

- README bleibt aktuell
- Quickstart funktioniert noch
- Fehlermeldungen sind verständlich
- Logs helfen bei der Fehlersuche
- neue Kernlogik ist getestet
