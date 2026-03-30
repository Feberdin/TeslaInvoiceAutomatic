# TeslaInvoiceAutomatic

Kostenfreie Home-Assistant-Custom-Integration fuer den automatischen Download von Tesla-Laderechnungen als PDF und den Versand an eine hinterlegte E-Mail-Adresse.

## Zweck / Features

- Erkennt neue Tesla-Ladevorgaenge ueber die Tesla Fleet API.
- Laedt die zugehoerige Lade-Rechnung als PDF herunter.
- Speichert jede Rechnung lokal im Home-Assistant-Konfigurationsordner.
- Versendet das PDF als E-Mail-Anhang ueber SMTP.
- Merkt sich bereits versendete Rechnungen, damit nichts doppelt verschickt wird.
- Kann auch aeltere Rechnungen nachtraeglich aus der Ladehistorie importieren.
- Stellt einen Status-Sensor und zwei manuelle Services in Home Assistant bereit.

## Architektur in Kurzform

- `custom_components/tesla_invoice_automatic/api.py`
  Kapselt Tesla Fleet API, Token-Refresh und klare Fehlermeldungen.
- `custom_components/tesla_invoice_automatic/coordinator.py`
  Pollt neue Ladesessions, speichert PDFs und verschickt E-Mails.
- `custom_components/tesla_invoice_automatic/emailer.py`
  Baut und sendet die SMTP-E-Mail mit PDF-Anhang.
- `custom_components/tesla_invoice_automatic/store.py`
  Speichert bereits verarbeitete Rechnungs-IDs persistent.
- `custom_components/tesla_invoice_automatic/sensor.py`
  Zeigt den letzten Versandstatus in Home Assistant an.

## Annahmen

- Home Assistant laeuft mit Custom-Component-Support.
- Du besitzt Zugriff auf die Tesla Fleet API und hast ein gueltiges `access_token`.
- Optional: `refresh_token`, `client_id` und `client_secret`, damit das Token automatisch erneuert werden kann.
- Deine Tesla-Freigaben decken Ladehistorie und Rechnungsabruf ab.
- Ein SMTP-Server ist vorhanden, der PDF-Anhaenge versenden darf.

## Quickstart

1. Dieses Repository per HACS oder manuell nach `config/custom_components/tesla_invoice_automatic` in deine Home-Assistant-Umgebung bringen.
2. Home Assistant neu starten.
3. In Home Assistant `Einstellungen -> Geraete & Dienste -> Integration hinzufuegen` und nach `Tesla Invoice Automatic` suchen.
4. Tesla- und SMTP-Daten eintragen.
5. Nach dem ersten abgeschlossenen Ladevorgang pruefen, ob der Sensor auf `sent` springt und die PDF im lokalen Invoice-Ordner liegt.

## Konfiguration

Pflichtfelder:

- `vin`
- `access_token`
- `recipient_email`
- `sender_email`
- `smtp_host`
- `smtp_port`
- `smtp_security`

Empfohlene Zusatzfelder:

- `refresh_token`
- `client_id`
- `client_secret`
- `poll_interval_minutes`
- `download_timeout_seconds`

Standardwerte:

- Tesla API Basis-URL: `https://fleet-api.prd.eu.vn.cloud.tesla.com`
- Tesla Token-URL: `https://auth.tesla.com/oauth2/v3/token`
- Polling: `15` Minuten
- SMTP-Port: `587`
- Timeout: `30` Sekunden

## Manuelle Ausloesung

Service in Home Assistant:

- `tesla_invoice_automatic.send_latest_invoice`
- `tesla_invoice_automatic.send_historical_invoices`

Optionales Feld:

- `entry_id`
  Wenn gesetzt, wird nur ein bestimmter Konfigurationseintrag aktualisiert.

Zusaetzliche Felder fuer historische Rechnungen:

- `days_back`
  Standard `365`. So weit in die Vergangenheit wird die Ladehistorie betrachtet.
- `max_invoices`
  Standard `50`. Begrenzt die Anzahl pro Lauf.
- `include_processed`
  Wenn `true`, werden auch bereits bekannte Rechnungen erneut versendet.

## Lokale Ablage

Heruntergeladene Rechnungen werden hier gespeichert:

- `config/tesla_invoice_automatic/invoices/<invoice_id>.pdf`

## So startest du es

Projekt lokal testen:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pytest
pytest -q
```

In Home Assistant:

```bash
cp -R custom_components/tesla_invoice_automatic /pfad/zu/homeassistant/config/custom_components/
```

Oder per HACS als Custom Repository einbinden. Die Datei [hacs.json](/Users/joachim.stiegler/TeslaInvoiceAutomatic/hacs.json) ist bereits vorbereitet.

Danach Home Assistant neu starten und die Integration ueber die UI einrichten.

## So debugst du es

Typische Fehler:

- `Pflichtfeld 'access_token' fehlt`
  Integrationseinstellungen pruefen.
- `Tesla API lehnt das Access-Token auch nach einem Refresh ab`
  `client_id`, `client_secret`, `refresh_token` und Tesla-Scopes kontrollieren.
- `Tesla lieferte ... keinen PDF-Inhalt zurueck`
  Pruefen, ob Tesla fuer diese Session wirklich eine Rechnung bereitstellt.
- `E-Mail mit Tesla-Rechnung konnte nicht gesendet werden`
  SMTP-Host, Port, TLS-Modus und Login pruefen.

Wo nachsehen:

- Home Assistant Logs fuer Laufzeitfehler.
- Sensor-Attribute fuer `last_error`, `last_invoice_id`, `last_email_at`, `last_history_import_at`, `last_history_days`.
- Lokale PDF-Dateien unter `config/tesla_invoice_automatic/invoices/`.
- Home Assistant Storage pro Config-Entry fuer bereits verarbeitete Rechnungs-IDs.

Empfohlene Log-Konfiguration in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tesla_invoice_automatic: debug
```

## Security-Hinweise

- Tesla OAuth-Daten und SMTP-Passwoerter niemals in Git committen.
- Fuer SMTP nach Moeglichkeit ein App-Passwort statt des Hauptpassworts verwenden.
- Logs maskieren keine Geheimnisse automatisch, wenn externe Systeme komplette Requests loggen. Daher Tokens nie manuell in Logs kopieren.
- Begrenze Tesla- und Mail-Rechte so stark wie moeglich.

## Troubleshooting

- Wenn keine Rechnung auftaucht, pruefe zuerst, ob Tesla fuer den Ladevorgang bereits eine Invoice-ID liefert.
- Wenn Rechnungen doppelt verschickt werden, den Storage-Status und die gespeicherten Invoice-IDs kontrollieren.
- Wenn du aeltere Rechnungen brauchst, den Service `tesla_invoice_automatic.send_historical_invoices` mit `days_back` und `max_invoices` ausfuehren.
- Wenn nach Home-Assistant-Neustart nichts mehr geht, Integration einmal oeffnen und Token aktualisieren.

## Lizenz-Hinweis

Das Projekt steht unter der MIT-Lizenz. Details siehe [LICENSE](/Users/joachim.stiegler/TeslaInvoiceAutomatic/LICENSE).
