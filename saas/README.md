# TeslaInvoiceAutomatic SaaS MVP

Diese Version ist ein dockerfähiger MVP zum Testen auf Unraid oder lokal mit Docker Compose. Die App enthält bereits:

- eine Web-Oberfläche unter `http://localhost:8000`
- eine API für Demo-User, Demo-Tesla-Verbindung, Sync und Rechnungsübersicht
- einen Worker, der regelmäßig neue Demo-Rechnungen erzeugt und verarbeitet
- Speicherung von Rechnungen in PostgreSQL plus PDF-Ablage im Volume
- Mail-Versand als nachvollziehbares Demo-Outbox-Log
- einen Unraid-freundlichen Einzelcontainer-Modus für appartige Installation

Wichtig: Diese Version nutzt absichtlich einen **Demo-Tesla-Adapter**. So kannst du den kompletten Ablauf testen, ohne an echter Tesla-OAuth, Tesla-Secrets oder Fleet-Freigaben zu blockieren. Die Architektur ist bereits so getrennt, dass später ein echter Tesla-Provider eingebaut werden kann.

## Kurzplan

1. FastAPI liefert API und Web-Oberfläche aus einem Container.
2. PostgreSQL speichert User, Tesla-Accounts, Fahrzeuge, Rechnungen und Mail-Einstellungen.
3. Ein Worker-Container führt alle `SYNC_INTERVAL_SECONDS` einen Rechnungssync aus.
4. Ein Demo-Tesla-Client erzeugt realistisch wirkende Ladesessions und PDF-Rechnungen.
5. PDFs landen im gemounteten Datenverzeichnis und können im Dashboard heruntergeladen werden.
6. Mailversand wird im MVP in eine `email-outbox.log` geschrieben, damit man alles nachvollziehen kann.
7. Kernlogik ist so gekapselt, dass ein echter Tesla OAuth/Fleet-Adapter später ergänzt werden kann.

## Annahmen

- Zielsystem: Unraid mit Docker App / Docker Compose Unterstützung
- Testbetrieb: zunächst Demo-Modus statt produktiver Tesla OAuth
- Speicher: lokales Docker-Volume statt S3/MinIO im ersten Schritt
- Authentifizierung: Für den MVP nur Demo-User per E-Mail, kein produktives Login-System
- HTTPS/Reverse Proxy: später über Unraid-Setup wie Nginx Proxy Manager oder Traefik

## Dateibaum

```text
.
├── .env.example
├── .gitignore
├── CONTRIBUTING.md
├── README.md
├── docker-compose.yml
└── backend
    ├── Dockerfile
    ├── requirements.txt
    ├── app
    │   ├── __init__.py
    │   ├── config.py
    │   ├── core_logic.py
    │   ├── database.py
    │   ├── domain.py
    │   ├── logging_config.py
    │   ├── main.py
    │   ├── models.py
    │   ├── pdf_utils.py
    │   ├── schemas.py
    │   ├── utils.py
    │   ├── worker.py
    │   ├── routes
    │   │   ├── __init__.py
    │   │   ├── api.py
    │   │   └── pages.py
    │   ├── services
    │   │   ├── __init__.py
    │   │   ├── emailer.py
    │   │   ├── storage.py
    │   │   ├── sync.py
    │   │   └── tesla.py
    │   ├── static
    │   │   ├── dashboard.js
    │   │   └── styles.css
    │   └── templates
    │       ├── base.html
    │       ├── dashboard.html
    │       └── index.html
    └── tests
        ├── test_core_logic.py
        └── test_pdf_and_validation.py
```

## Quickstart

### 1. Konfiguration vorbereiten

```bash
cp .env.example .env
```

Du kannst die Standardwerte zunächst so lassen.

### 2. Stack starten

```bash
docker compose up --build
```

### 3. Im Browser öffnen

```text
http://localhost:8000
```

## Unraid als App

Wenn du die Demo-Version lieber wie eine echte Unraid-App installieren willst, ist jetzt auch das vorbereitet:

1. Docker-Image nach GHCR veröffentlichen
2. `unraid/TeslaInvoiceAutomatic-SaaS.xml` auf Unraid unter
   `/boot/config/plugins/dockerMan/templates-user/` ablegen
3. App über das User-Template installieren

Details dazu stehen in `../unraid/README.md`, wenn dieses Projekt als `saas/` Unterordner im Haupt-Repository liegt.

## Test-Flow

1. Auf `/dashboard` gehen
2. Demo-E-Mail eintragen
3. `Demo-Nutzer anlegen` klicken
4. `Tesla Demo verbinden` klicken
5. optional Empfänger speichern
6. `Sync jetzt auslösen` klicken
7. Rechnungen in der Tabelle prüfen und PDFs herunterladen

## Zentrale Dateien

### `backend/app/services/tesla.py`

Erzeugt Demo-Fahrzeuge, Demo-Ladevorgänge und echte PDF-Dateien für den Testbetrieb.

### `backend/app/services/sync.py`

Kernlogik für:

- neue Sessions erkennen
- Rechnungen deduplizieren
- PDF speichern
- Mail-Zusammenfassung schreiben
- Sync-Status aktualisieren

### `backend/app/routes/api.py`

Stellt die Test-API bereit, die auch vom Dashboard verwendet wird.

### `backend/app/worker.py`

Führt den regelmäßigen Hintergrundsync aus.

### `backend/app/unraid_main.py`

Startet API und Worker gemeinsam in einem Container, damit Unraid die Demo einfach als einzelne App installieren kann.

## Konfiguration

Wichtige Umgebungsvariablen:

- `DATABASE_URL`: PostgreSQL oder SQLite
- `DATA_DIR`: Speicherort für PDFs und Mail-Outbox
- `SYNC_INTERVAL_SECONDS`: Worker-Intervall
- `LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`
- `DEMO_MODE`: muss für diesen MVP `true` sein

## Logging / Debug

### Log-Level

- `DEBUG`: sehr ausführlich, ideal bei Fehlersuche
- `INFO`: Standard für normalen Betrieb
- `WARNING`: ungewöhnliche, aber nicht kritische Situationen
- `ERROR`: Fehler mit Handlungsbedarf

### Wo nachsehen?

- API / Worker Logs:

```bash
docker compose logs -f api worker
```

- Datenbank Logs:

```bash
docker compose logs -f db
```

- PDF-Dateien:

```text
./data/invoices
```

- Demo-Mailausgang:

```text
./data/email-outbox.log
```

## Troubleshooting

### Fehler: Port 8000 ist belegt

Ändere im `docker-compose.yml` den Host-Port, zum Beispiel auf `8080:8000`.

### Fehler: Datenbankverbindung schlägt fehl

Prüfen:

- läuft der `db`-Container?
- ist `DATABASE_URL` korrekt?
- ist der Healthcheck von PostgreSQL grün?

### Fehler: Es erscheinen keine Rechnungen

Prüfen:

- wurde zuerst ein Demo-Nutzer angelegt?
- wurde `Tesla Demo verbinden` ausgeführt?
- lief danach ein manueller Sync?
- zeigen `docker compose logs -f worker api` Warnungen oder Fehler?

## Security-Hinweise

- Diese Version ist eine Demo-Basis und nicht produktiv gehärtet.
- Keine echten Tesla-Passwörter speichern.
- Später müssen OAuth-Tokens verschlüsselt gespeichert werden.
- Für Internetbetrieb nur hinter HTTPS und Reverse Proxy veröffentlichen.
- Secrets gehören in Unraid-Container-Variablen oder Secret-Management, nicht ins Git-Repo.

## Lokale Tests

Die Kernlogik-Tests funktionieren ohne Docker und ohne externe Pakete:

```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests
```

## Lizenz-Hinweis

Bitte ergänze hier später die gewünschte Projektlizenz, falls dieses neue SaaS-Repo veröffentlicht wird.
