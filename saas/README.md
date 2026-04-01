# TeslaInvoiceAutomatic SaaS MVP

Diese Version ist ein Docker-first Teststand fuer Unraid und lokale Docker-Umgebungen. Der Fokus liegt jetzt nicht mehr nur auf Demo-Rechnungen, sondern auf dem spaeteren SaaS-Nutzerfluss:

- Konto registrieren und einloggen
- eine oder mehrere VINs hinterlegen
- Empfaenger fuer Rechnungen speichern
- Testrechnung per SMTP oder Outbox pruefen
- Demo-Rechnungen erzeugen, archivieren und herunterladen
- Buchhaltungssysteme vorerst als sichtbare Platzhalter auswaehlen

Wichtig: Die Tesla-Seite laeuft in diesem Build noch bewusst im `DEMO_MODE`. Das heisst: Login, VIN-Verwaltung, Session, Mailversand und Archiv sind echt testbar, die Tesla-Quelle selbst ist aber noch ein Demo-Adapter statt echter Tesla Fleet OAuth.

## Kurzplan

1. FastAPI liefert Landingpage, Registrierung, Login, Dashboard und JSON-API.
2. Session-Cookies halten den angemeldeten Nutzer im Browser, damit VINs und Rechnungen nicht ueber E-Mail-Felder verwechselt werden.
3. Pro Nutzer koennen mehrere VINs gespeichert werden.
4. Ein Demo-Tesla-Adapter erzeugt pro VIN nachvollziehbare Ladevorgaenge und Rechnungs-PDFs.
5. Rechnungen landen im Datenverzeichnis und im Dashboard-Archiv.
6. E-Mails gehen entweder ueber echten SMTP oder nachvollziehbar in `email-outbox.log`.
7. Buchhaltungssysteme sind bereits als UI-Platzhalter vorhanden, aber noch ohne echten Export.

## Annahmen

- Zielsystem: Unraid mit Docker App oder lokales Docker Compose
- Aktueller Tesla-Modus: `DEMO_MODE=true`
- Mailversand: SMTP ist optional, Outbox-Log steht immer zur Verfuegung
- Persistenz: Unraid-App nutzt SQLite im `/data`-Volume, Docker Compose nutzt PostgreSQL
- Reverse Proxy / HTTPS: spaeter ueber Unraid-Setup wie Nginx Proxy Manager oder Traefik

## Features

- Registrierung und Login per E-Mail + Passwort
- Session-basierter Dashboard-Zugang
- mehrere VINs pro Nutzer
- gespeicherte Versandempfaenger pro Nutzer
- Testrechnung an gespeicherte oder abweichende Test-Adresse
- Demo-Sync fuer neue Rechnungen
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
    │   ├── logging_config.py
    │   ├── main.py
    │   ├── models.py
    │   ├── pdf_utils.py
    │   ├── schemas.py
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
    │   │   └── tesla.py
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
        └── test_pdf_and_validation.py
```

## Zentrale Dateien

### `backend/app/routes/api.py`

Verarbeitet Registrierung, Login, Session, VIN-Anlage, Versand-Einstellungen, Testmail, Sync und Rechnungsdownload.

### `backend/app/services/emailer.py`

Schreibt jede ausgehende Nachricht zusaetzlich ins Outbox-Log und kann bei gesetzten SMTP-Variablen echte E-Mails verschicken.

### `backend/app/services/sync.py`

Erzeugt neue Demo-Rechnungen pro VIN, speichert PDFs und verschickt Zusammenfassungen an die hinterlegten Empfaenger.

### `backend/app/templates/auth.html`

Startpunkt fuer neue Nutzer mit Registrierung und Login.

### `backend/app/templates/dashboard.html`

Cockpit fuer VINs, Mailversand, Buchhaltungsplatzhalter und Rechnungsarchiv.

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
3. im Dashboard eine oder mehrere VINs hinterlegen
4. Versandempfaenger speichern
5. optional Test-E-Mail-Adresse eintragen
6. `Testrechnung senden` klicken
7. `Demo-Sync ausloesen` klicken
8. PDFs im Archiv herunterladen

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

- `DEBUG`: zeigt zusaetzlich SMTP-Versuchsdetails, Outbox-Schreibzugriffe und ausfuehrlichere Ablauflogik
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

Das ist korrekt, solange dem Konto noch kein Fahrzeug zugeordnet wurde.

### Fehler: Rechnungsdatei nicht gefunden

Pruefen:

- ist `/data` in Unraid oder Docker Compose wirklich gemountet?
- existiert das Verzeichnis `invoices/` unter dem Volume?
- wurde das Appdata- oder Datenverzeichnis versehentlich geloescht?

## Security-Hinweise

- Tesla-Passwoerter werden in diesem MVP nicht verwendet oder gespeichert.
- SMTP-Passwoerter nur als Umgebungsvariable oder Unraid-Masked-Variable setzen.
- `SECRET_KEY` vor oeffentlichem oder laengerem Betrieb ersetzen.
- Diese Build-Stufe ist ein Test-MVP und noch keine vollstaendig gehaertete SaaS-Produktivversion.

## Lizenz-Hinweis

Der Lizenzstatus folgt dem Haupt-Repository [Feberdin/TeslaInvoiceAutomatic](https://github.com/Feberdin/TeslaInvoiceAutomatic).
