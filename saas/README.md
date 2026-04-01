# TeslaInvoiceAutomatic SaaS MVP

Diese Version ist ein Docker-first Teststand fuer Unraid und lokale Docker-Umgebungen. Der aktuelle Fokus liegt auf einem testbaren SaaS-Nutzerfluss mit echtem Mailversand und zwei echten Tesla-Verbindungswegen:

- Konto registrieren und einloggen
- eine oder mehrere VINs hinterlegen
- Tesla per offiziellem Fleet OAuth verbinden
- oder Tesla per inoffiziellem Token-Import anbinden
- Betreiber koennen im separaten Admin-Menue den Tesla-Fleet-Public-Key erzeugen und die Partner-App registrieren
- Empfaenger fuer Rechnungen speichern
- Testrechnung per SMTP oder Outbox pruefen
- Circula als erstes echtes Buchhaltungsziel per E-Mail bedienen
- Demo- oder Live-Rechnungen erzeugen, archivieren und herunterladen
- weitere Buchhaltungssysteme als klar markierte Platzhalter sehen

Wichtig: Diese Build-Stufe unterstuetzt bewusst beide Varianten parallel. Der Fleet-Weg ist der offizielle SaaS-Pfad, der inoffizielle Token-Import ist der praktische Self-Hosted-Weg ohne Fleet-Billing. `DEMO_MODE=true` bleibt als sicherer Fallback sinnvoll, bis mindestens eine echte Tesla-Verbindung vorhanden ist.

## Kurzplan

1. FastAPI liefert Landingpage, Registrierung, Login, Dashboard und JSON-API.
2. Session-Cookies halten den angemeldeten Nutzer im Browser, damit VINs und Rechnungen nicht ueber E-Mail-Felder verwechselt werden.
3. Pro Nutzer koennen mehrere VINs gespeichert werden.
4. Ein offizieller Tesla-Fleet-Client startet den OAuth-Login, tauscht den Callback-Code gegen Tokens und ruft pro VIN echte Charging-Invoices ab.
5. Ein inoffizieller Owner-Token-/Cache-Import bleibt als Self-Hosted-Weg ohne Fleet-Billing verfuegbar, liegt fuer Beta-Tests aber nur im Admin-Debug-Menue.
6. Betreiber koennen im separaten Admin-Menue den Tesla-Fleet-Public-Key erzeugen, unter `/.well-known/...` ausliefern und den Tesla-Partner-Register-Call fuer die Region ausloesen.
7. Der Hintergrundsync laeuft ueber einen konfigurierbaren Docker-/Unraid-Intervall (`SYNC_INTERVAL_MINUTES` bevorzugt `SYNC_INTERVAL_SECONDS`).
8. Wenn kein echter Tesla-Zugang verbunden ist, erzeugt der Demo-Tesla-Adapter pro VIN nachvollziehbare Test-Rechnungen.
9. Rechnungen landen im Datenverzeichnis und im Dashboard-Archiv.
10. E-Mails gehen entweder ueber echten SMTP oder nachvollziehbar in `email-outbox.log`.
11. Circula ist als erster einfacher Buchhaltungsweg implementiert. Weitere Ziele bleiben sichtbar, aber klar als noch nicht umgesetzt markiert.

## Annahmen

- Zielsystem: Unraid mit Docker App oder lokales Docker Compose
- Aktueller Tesla-Modus: `DEMO_MODE=true` als Fallback, echter Tesla-Zugang wird im Dashboard per Fleet OAuth oder inoffiziellem Token-Import verbunden
- Mailversand: SMTP ist optional, Outbox-Log steht immer zur Verfuegung
- Persistenz: Unraid-App nutzt SQLite im `/data`-Volume, Docker Compose nutzt PostgreSQL
- Reverse Proxy / HTTPS: spaeter ueber Unraid-Setup wie Nginx Proxy Manager oder Traefik

## Features

- Registrierung und Login per E-Mail + Passwort
- Session-basierter Dashboard-Zugang
- mehrere VINs pro Nutzer
- offizieller Tesla-Fleet-Login direkt aus dem Dashboard
- separates Admin-Menue fuer Betreiber mit Public-Key-Status, Partner-Register-Button und Tesla-Verify
- Admin-Debug mit manueller VIN-Anlage, Testmail-Override und inoffiziellem Tesla-Owner-Import ueber Refresh-Token oder TeslaPy-/tesla_ha-`cache.json`
- gespeicherte Versandempfaenger pro Nutzer
- Testrechnung an gespeicherte Empfaenger im Dashboard plus abweichende Test-Adresse im Admin-Debug
- Live-Sync fuer echte Tesla-Rechnungen oder Demo-Sync als Fallback
- PDF-Download aus dem Archiv
- Circula-Versand ueber `receipts@in.circula.com` mit Mitarbeiter-Absenderadresse
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
    │   ├── admin.py
    │   ├── config.py
    │   ├── database.py
    │   ├── domain.py
    │   ├── errors.py
    │   ├── logging_config.py
    │   ├── main.py
    │   ├── models.py
    │   ├── pdf_utils.py
    │   ├── schemas.py
    │   ├── tesla_modes.py
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
    │   │   ├── tesla_fleet.py
    │   │   ├── tesla_partner.py
    │   │   └── tesla_owner.py
    │   ├── static
    │   │   ├── admin.js
    │   │   ├── auth.js
    │   │   ├── dashboard.js
    │   │   └── styles.css
    │   └── templates
    │       ├── admin.html
    │       ├── auth.html
    │       ├── base.html
    │       ├── dashboard.html
    │       └── index.html
    └── tests
        ├── test_auth_and_vin.py
        ├── test_core_logic.py
        ├── test_pdf_and_validation.py
        ├── test_tesla_fleet.py
        ├── test_tesla_modes.py
        └── test_tesla_owner.py
```

## Zentrale Dateien

### `backend/app/routes/api.py`

Verarbeitet Registrierung, Login, Session, Tesla OAuth, manuellen Tesla-Import, VIN-Anlage, Versand-Einstellungen, Testmail, Sync und Rechnungsdownload.

### `backend/app/services/tesla_fleet.py`

Startet den offiziellen Tesla OAuth-Flow, verarbeitet den Callback, refreshed Fleet-Tokens und ruft Tesla-Charging-History sowie PDF-Rechnungen fuer echte VINs ab.

### `backend/app/services/tesla_partner.py`

Erzeugt den Tesla-Fleet-Public-Key, liefert Status fuer das Admin-Menue, holt Partner-Tokens und fuehrt den Tesla-Partner-Register- sowie Verify-Call aus.

### `backend/app/services/tesla_owner.py`

Bleibt als technischer Fallback fuer manuell importierte Tesla Owner-/TeslaPy-Tokens erhalten.

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

Optional fuer echten Mailtest und beide Tesla-Wege in `.env` setzen:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=dein-user
SMTP_PASSWORD=dein-passwort
SMTP_USE_TLS=true
SMTP_USE_SSL=false
DEFAULT_FROM_EMAIL=no-reply@example.com
SECRET_KEY=bitte-einen-langen-zufaelligen-wert-setzen
SYNC_INTERVAL_MINUTES=30
ENABLE_TESLA_FLEET_OAUTH=true
ENABLE_TESLA_OWNER_IMPORT=true
ADMIN_EMAILS=admin@example.com
TESLA_CLIENT_ID=deine-tesla-client-id
TESLA_CLIENT_SECRET=dein-tesla-client-secret
TESLA_FLEET_API_BASE_URL=https://fleet-api.prd.eu.vn.cloud.tesla.com
TESLA_PARTNER_TOKEN_SCOPE=openid user_data vehicle_device_data vehicle_cmds vehicle_charging_cmds
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
3. im Dashboard `Offiziell mit Tesla verbinden` nutzen
4. Versandempfaenger speichern
5. optional `Circula` aktivieren und eine Mitarbeiter-Absenderadresse hinterlegen
6. `Testrechnung senden` klicken
7. `Fleet-Sync ausloesen`
8. PDFs im Archiv herunterladen

Beta-Debug nur fuer Betreiber:

1. `/admin` oeffnen
2. dort bei Bedarf eine abweichende Test-E-Mail senden
3. manuelle VINs anlegen oder entfernen
4. den inoffiziellen Tesla-Import fuer Vergleichstests nutzen

## Tesla Fleet Admin-Menue

Wenn dein Betreiberkonto in `ADMIN_EMAILS` enthalten ist, erscheint zusaetzlich ein separates `/admin`-Menue.

Dort kannst du:

1. den Tesla-Fleet-Public-Key erzeugen
2. die Well-Known-URL `/.well-known/appspecific/com.tesla.3p.public-key.pem` pruefen
3. den Tesla-Partner-Register-Call fuer die aktuelle Region ausloesen
4. den Tesla-Status pruefen, ob der Public Key bereits registriert ist

Das Admin-Menue ist fuer den Betreiber gedacht. Endkunden brauchen diesen Schritt spaeter nicht mehr, sondern nur den offiziellen Tesla-Login.

## Echte Tesla-Daten testen

Es gibt aktuell zwei Wege:

1. Offizieller Tesla-Login ueber Fleet API
   Der empfohlene Weg fuer den ersten Beta-Test. Setze als Betreiber `ENABLE_TESLA_FLEET_OAUTH=true`, `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET` und die passende `TESLA_FLEET_API_BASE_URL`. Danach klicken Endkunden im Dashboard auf `Offiziell mit Tesla verbinden`.

2. Inoffizieller Token-Import ohne Fleet-Billing
   Der praktische Weg fuer Self-Hosted-Tests. Setze `ENABLE_TESLA_OWNER_IMPORT=true` und trage im Admin-Debug eine Tesla-Konto-E-Mail plus Refresh-Token oder TeslaPy-/tesla_ha-Cache ein.

Danach:

1. echte VIN speichern
2. den gewuenschten Tesla-Weg verbinden
3. `Fleet-Sync` oder den Debug-Import ausloesen
4. Rechnungs-PDFs im Archiv oder Maileingang pruefen

## E-Mail-Test: Was passiert genau?

- Ohne SMTP:
  Die Mail wird in `email-outbox.log` protokolliert. So kannst du Betreff, Empfaenger und Anhaenge pruefen, ohne echten Versand.
- Mit SMTP:
  Die Testrechnung und die Sync-Zusammenfassung werden an den konfigurierten Mailserver uebergeben.
- Mit abweichender Testadresse:
  Im Admin-Debug kannst du einmalig eine andere Zieladresse fuer den Testversand angeben, ohne die dauerhaft gespeicherten Empfaenger zu ersetzen.

## Circula

Circula ist als erster einfacher Buchhaltungsweg bereits umgesetzt:

1. aktiviere `Circula` in den Versand-Einstellungen
2. trage die Mitarbeiter-E-Mail ein, die bei Circula dem Beleg zugeordnet werden soll
3. der Sync sendet neue Rechnungs-PDFs zusaetzlich an `receipts@in.circula.com`

Wichtig:

- Die Mitarbeiter-E-Mail wird als Absender verwendet.
- Wenn `Circula` aktiv ist, aber keine Mitarbeiter-E-Mail hinterlegt wurde, blockiert die Validierung den Speichervorgang bewusst frueh.
- Die anderen Buchhaltungsziele bleiben sichtbar, sind aber noch nicht implementiert.

## Unraid als App

Fuer Unraid ist ein User-Template vorbereitet:

- `unraid/TeslaInvoiceAutomatic-SaaS.xml`

Wichtige Variablen in Unraid:

- `APP_BASE_URL`
- `SECRET_KEY`
- `DATABASE_URL`
- `DATA_DIR`
- `DEMO_MODE=true`
- `SYNC_INTERVAL_MINUTES`
- `LOG_LEVEL`
- `DEFAULT_FROM_EMAIL`
- `ENABLE_TESLA_FLEET_OAUTH`
- `ENABLE_TESLA_OWNER_IMPORT`
- `ADMIN_EMAILS`
- `TESLA_CLIENT_ID`
- `TESLA_CLIENT_SECRET`
- `TESLA_FLEET_API_BASE_URL`
- `TESLA_OAUTH_SCOPE`
- `TESLA_OAUTH_REDIRECT_PATH`
- `TESLA_PARTNER_TOKEN_SCOPE`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS`
- `SMTP_USE_SSL`

Details stehen in [unraid/README.md](./unraid/README.md).

## Sync-Intervall fuer den Beta-Test

- `SYNC_INTERVAL_MINUTES` ist der bevorzugte Regler fuer Docker und Unraid.
- Wenn `SYNC_INTERVAL_MINUTES` groesser als `0` ist, wird `SYNC_INTERVAL_SECONDS` ignoriert.
- Beispiel:

```env
SYNC_INTERVAL_MINUTES=30
```

Das sorgt fuer einen automatischen Abruf alle 30 Minuten.

## Tests lokal ausfuehren

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend python3 -m unittest discover -s backend/tests
```

## Logging / Debug

### Log-Level

- `DEBUG`: zeigt zusaetzlich SMTP-Versuchsdetails, Tesla-OAuth-Status, Token-Import, Tesla-Sync-Auswahl und Outbox-Schreibzugriffe
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
