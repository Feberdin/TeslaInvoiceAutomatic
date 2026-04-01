# TeslaInvoiceAutomatic SaaS MVP

Diese Version ist ein Docker-first Teststand fuer Unraid und lokale Docker-Umgebungen. Der aktuelle Fokus liegt auf einem testbaren SaaS-Nutzerfluss mit echtem Mailversand und einer live-faehigen Tesla-Anbindung per Token-/Cache-Import:

- Konto registrieren und einloggen
- eine oder mehrere VINs hinterlegen
- Tesla-Zugang per TeslaPy-/tesla_ha-Cache oder Tesla-Tokens importieren
- Empfaenger fuer Rechnungen speichern
- Testrechnung per SMTP oder Outbox pruefen
- Demo- oder Live-Rechnungen erzeugen, archivieren und herunterladen
- Buchhaltungssysteme vorerst als sichtbare Platzhalter auswaehlen

Wichtig: Echte Tesla-Rechnungen lassen sich in dieser Build-Stufe ueber importierte Tesla Owner-/TeslaPy-Tokens testen. Die offizielle Tesla Fleet OAuth-Partnerregistrierung ist damit noch nicht ersetzt, aber du kannst den realen Abruf von Charging-History und PDF-Rechnungen bereits verifizieren. `DEMO_MODE=true` bleibt als sicherer Fallback sinnvoll.

## Kurzplan

1. FastAPI liefert Landingpage, Registrierung, Login, Dashboard und JSON-API.
2. Session-Cookies halten den angemeldeten Nutzer im Browser, damit VINs und Rechnungen nicht ueber E-Mail-Felder verwechselt werden.
3. Pro Nutzer koennen mehrere VINs gespeichert werden.
4. Ein Live-Tesla-Client kann Owner-/TeslaPy-Tokens refreshen und pro VIN echte Charging-Invoices abrufen.
5. Wenn kein echter Tesla-Zugang verbunden ist, erzeugt der Demo-Tesla-Adapter pro VIN nachvollziehbare Test-Rechnungen.
6. Rechnungen landen im Datenverzeichnis und im Dashboard-Archiv.
7. E-Mails gehen entweder ueber echten SMTP oder nachvollziehbar in `email-outbox.log`.
8. Buchhaltungssysteme sind bereits als UI-Platzhalter vorhanden, aber noch ohne echten Export.

## Annahmen

- Zielsystem: Unraid mit Docker App oder lokales Docker Compose
- Aktueller Tesla-Modus: `DEMO_MODE=true` als Fallback, echter Tesla-Zugang wird im Dashboard importiert
- Mailversand: SMTP ist optional, Outbox-Log steht immer zur Verfuegung
- Persistenz: Unraid-App nutzt SQLite im `/data`-Volume, Docker Compose nutzt PostgreSQL
- Reverse Proxy / HTTPS: spaeter ueber Unraid-Setup wie Nginx Proxy Manager oder Traefik

## Features

- Registrierung und Login per E-Mail + Passwort
- Session-basierter Dashboard-Zugang
- mehrere VINs pro Nutzer
- Tesla-Import ueber TeslaPy-/tesla_ha-`cache.json` oder manuelle Tokens
- gespeicherte Versandempfaenger pro Nutzer
- Testrechnung an gespeicherte oder abweichende Test-Adresse
- Live-Sync fuer echte Tesla-Rechnungen oder Demo-Sync als Fallback
- PDF-Download aus dem Archiv
- sichtbare Platzhalter fuer DATEV, Lexoffice, sevDesk, Paperless, Dropbox und Google Drive
- DEBUG/INFO/WARNING/ERROR Logging fuer API, Worker und Mailpfad

## Dateibaum

```text
.
├── .env.example
├── .gitignore
├── CONTRIBUTING.md
├── README.md
├── docker-compose.yml
├── unraid
│   ├── README.md
│   ├── TeslaInvoiceAutomatic-SaaS.xml
│   └── icon.svg
└── backend
    ├── Dockerfile
    ├── requirements.txt
    ├── app
    │   ├── auth.py
    │   ├── config.py
    │   ├── database.py
    │   ├── domain.py
    │   ├── errors.py
    │   ├── logging_config.py
    │   ├── main.py
    │   ├── models.py
    │   ├── pdf_utils.py
    │   ├── schemas.py
    │   ├── token_store.py
    │   ├── unraid_main.py
    │   ├── utils.py
    │   ├── worker.py
    │   ├── routes
    │   │   ├── api.py
    │   │   └── pages.py
    │   ├── services
    │   │   ├── emailer.py
    │   │   ├── storage.py
    │   │   ├── sync.py
    │   │   ├── tesla.py
    │   │   └── tesla_owner.py
    │   ├── static
    │   │   ├── auth.js
    │   │   ├── dashboard.js
    │   │   └── styles.css
    │   └── templates
    │       ├── auth.html
    │       ├── base.html
    │       ├── dashboard.html
    │       └── index.html
    └── tests
        ├── test_auth_and_vin.py
        ├── test_core_logic.py
        ├── test_pdf_and_validation.py
        └── test_tesla_owner.py
```

## Zentrale Dateien

### `backend/app/routes/api.py`

Verarbeitet Registrierung, Login, Session, Tesla-Import, VIN-Anlage, Versand-Einstellungen, Testmail, Sync und Rechnungsdownload.

### `backend/app/services/tesla_owner.py`

Importiert TeslaPy-/tesla_ha-Caches oder manuelle Tokens, refreshed Owner-Tokens und ruft Tesla-Charging-History sowie PDF-Rechnungen fuer echte VINs ab.

### `backend/app/services/sync.py`

Waehlt automatisch zwischen echtem Tesla-Sync und Demo-Fallback, speichert PDFs und verschickt Zusammenfassungen an die hinterlegten Empfaenger.

### `backend/app/services/emailer.py`

Schreibt jede ausgehende Nachricht zusaetzlich ins Outbox-Log und kann bei gesetzten SMTP-Variablen echte E-Mails verschicken.

### `backend/app/templates/dashboard.html`

Cockpit fuer Tesla-Zugang, VINs, Mailversand, Buchhaltungsplatzhalter und Rechnungsarchiv.

## Quickstart mit Docker Compose

### 1. Konfiguration vorbereiten

```bash
cp .env.example .env
```

Optional fuer echten Mailtest in `.env` setzen:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=dein-user
SMTP_PASSWORD=dein-passwort
SMTP_USE_TLS=true
SMTP_USE_SSL=false
DEFAULT_FROM_EMAIL=no-reply@example.com
SECRET_KEY=bitte-einen-langen-zufaelligen-wert-setzen
```

### 2. Stack starten

```bash
docker compose up --build
```

### 3. Im Browser oeffnen

```text
http://localhost:8000
```

## Test-Flow im Browser

1. `/auth` oeffnen oder auf der Startseite `Registrieren / Login` klicken
2. neues Konto registrieren
3. optional im Dashboard einen TeslaPy-/tesla_ha-Cache oder Tesla-Tokens importieren
4. eine oder mehrere VINs hinterlegen
5. Versandempfaenger speichern
6. optional Test-E-Mail-Adresse eintragen
7. `Testrechnung senden` klicken
8. `Tesla-Sync ausloesen` oder `Demo-Sync ausloesen` klicken
9. PDFs im Archiv herunterladen

## Echte Tesla-Daten testen

Es gibt aktuell zwei praxistaugliche Wege:

1. TeslaPy-/tesla_ha-Cache importieren
   Der empfohlene Weg. Kopiere den kompletten Inhalt deiner bestehenden `cache.json` in das Dashboard-Feld `TeslaPy / tesla_ha cache.json`.

2. Refresh-Token direkt eintragen
   Trage im Dashboard die Tesla-Konto-E-Mail und mindestens das Refresh-Token ein. Ein Access-Token ist optional, beschleunigt aber den ersten Test.

Danach:

1. echte VIN speichern
2. `Tesla verbinden` klicken
3. `Tesla-Sync ausloesen` klicken
4. Rechnungs-PDFs im Archiv oder Maileingang pruefen

## E-Mail-Test: Was passiert genau?

- Ohne SMTP:
  Die Mail wird in `email-outbox.log` protokolliert. So kannst du Betreff, Empfaenger und Anhaenge pruefen, ohne echten Versand.
- Mit SMTP:
  Die Testrechnung und die Sync-Zusammenfassung werden an den konfigurierten Mailserver uebergeben.
- Mit abweichender Testadresse:
  Im Dashboard kannst du einmalig eine andere Zieladresse fuer den Testversand angeben, ohne die dauerhaft gespeicherten Empfaenger zu ersetzen.

## Unraid als App

Fuer Unraid ist ein User-Template vorbereitet:

- `unraid/TeslaInvoiceAutomatic-SaaS.xml`

Wichtige Variablen in Unraid:

- `APP_BASE_URL`
- `SECRET_KEY`
- `DATABASE_URL`
- `DATA_DIR`
- `DEMO_MODE=true`
- `LOG_LEVEL`
- `DEFAULT_FROM_EMAIL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS`
- `SMTP_USE_SSL`

Details stehen in [unraid/README.md](./unraid/README.md).

## Tests lokal ausfuehren

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend python3 -m unittest discover -s backend/tests
```

## Logging / Debug

### Log-Level

- `DEBUG`: zeigt zusaetzlich SMTP-Versuchsdetails, Token-Import, Tesla-Sync-Auswahl und Outbox-Schreibzugriffe
- `INFO`: Standard fuer normalen Testbetrieb
- `WARNING`: ungewoehnliche Situationen ohne harten Fehler
- `ERROR`: nur Fehler

### Wo nachsehen?

Docker Compose:

```bash
docker compose logs -f api worker db
```

Unraid:

- Container-Logs im Docker-Tab
- Volume-Inhalte unter deinem `/data`-Mount

Wichtige Dateien:

- Rechnungen: `data/invoices/`
- Mail-Outbox: `data/email-outbox.log`
- SQLite im Unraid-Einzelcontainer: `data/local_demo.db`

## Troubleshooting

### Fehler: Login klappt, aber Dashboard wirft wieder auf `/auth`

Pruefen:

- ist `SECRET_KEY` gesetzt?
- blockiert ein Reverse Proxy Cookies?
- ist die Browser-Session noch gueltig?

### Fehler: Testmail landet nur im Outbox-Log

Pruefen:

- ist `SMTP_HOST` gesetzt?
- stimmen `SMTP_PORT`, `SMTP_USE_TLS` und `SMTP_USE_SSL`?
- braucht der Server Login mit `SMTP_USERNAME` und `SMTP_PASSWORD`?
- zeigen die Container-Logs SMTP-Fehlerdetails?

### Fehler: Sync meldet, dass zuerst eine VIN angelegt werden muss

Das ist korrekt, solange dem aktiven Tesla-Modus noch kein Fahrzeug zugeordnet wurde.

### Fehler: Tesla-Verbindung wird gespeichert, aber Live-Sync scheitert

Pruefen:

- gehoert die gespeicherte VIN wirklich zu genau diesem Tesla-Konto?
- ist im Dashboard `Live Tesla` als aktive Quelle sichtbar?
- liefert `tesla_last_error` im Dashboard oder im Container-Log einen konkreten Tesla-Hinweis?
- hat der Container ausgehenden Internet-Zugriff?

### Fehler: Rechnungsdatei nicht gefunden

Pruefen:

- ist `/data` in Unraid oder Docker Compose wirklich gemountet?
- existiert das Verzeichnis `invoices/` unter dem Volume?
- wurde das Appdata- oder Datenverzeichnis versehentlich geloescht?

## Security-Hinweise

- Tesla-Passwoerter werden in diesem MVP nicht verwendet oder gespeichert.
- Importierte Tesla-Tokens werden in der Datenbank verschluesselt abgelegt.
- SMTP-Passwoerter nur als Umgebungsvariable oder Unraid-Masked-Variable setzen.
- `SECRET_KEY` vor oeffentlichem oder laengerem Betrieb ersetzen.
- Diese Build-Stufe ist ein Test-MVP und noch keine vollstaendig gehaertete SaaS-Produktivversion.

## Lizenz-Hinweis

Der Lizenzstatus folgt dem Haupt-Repository [Feberdin/TeslaInvoiceAutomatic](https://github.com/Feberdin/TeslaInvoiceAutomatic).
