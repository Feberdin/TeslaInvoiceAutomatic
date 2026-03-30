# TeslaInvoiceAutomatic

Kostenfreie Home-Assistant-Custom-Integration fuer den automatischen Versand bereits heruntergeladener Tesla-Rechnungen als PDF an eine hinterlegte E-Mail-Adresse.

## Zweck / Features

- Ueberwacht einen lokalen Ordner auf neue Tesla-Rechnungs-PDFs.
- Versendet das PDF als E-Mail-Anhang ueber SMTP.
- Merkt sich bereits versendete Rechnungen, damit nichts doppelt verschickt wird.
- Kann auch aeltere PDF-Dateien nachtraeglich erneut oder gesammelt versenden.
- Stellt einen Status-Sensor und zwei manuelle Services in Home Assistant bereit.

## Architektur in Kurzform

- `custom_components/tesla_invoice_automatic/api.py`
  Liest PDF-Dateien aus einem lokalen Watch-Ordner mit klaren Fehlermeldungen.
- `custom_components/tesla_invoice_automatic/coordinator.py`
  Pollt den Watch-Ordner und verschickt neue PDF-Dateien.
- `custom_components/tesla_invoice_automatic/emailer.py`
  Baut und sendet die SMTP-E-Mail mit PDF-Anhang.
- `custom_components/tesla_invoice_automatic/store.py`
  Speichert bereits verarbeitete Rechnungs-IDs persistent.
- `custom_components/tesla_invoice_automatic/sensor.py`
  Zeigt den letzten Versandstatus in Home Assistant an.

## Annahmen

- Home Assistant laeuft mit Custom-Component-Support.
- Du laedst die echte Tesla-Rechnungs-PDF manuell herunter.
- Home Assistant kann auf den konfigurierten lokalen Ordner lesen.
- Ein SMTP-Server ist vorhanden, der PDF-Anhaenge versenden darf.

## Quickstart

1. Dieses Repository per HACS oder manuell nach `config/custom_components/tesla_invoice_automatic` in deine Home-Assistant-Umgebung bringen.
2. Home Assistant neu starten.
3. In Home Assistant `Einstellungen -> Geraete & Dienste -> Integration hinzufuegen` und nach `Tesla Invoice Automatic` suchen.
4. PDF-Ordner und SMTP-Daten eintragen.
5. Eine echte Tesla-Rechnungs-PDF in den Watch-Ordner legen.
6. Pruefen, ob der Sensor auf `sent` springt und die Datei per E-Mail verschickt wurde.

## Konfiguration

Pflichtfelder:

- `watch_directory`
- `file_pattern`
- `recipient_email`
- `sender_email`
- `smtp_host`
- `smtp_port`
- `smtp_security`

Empfohlene Zusatzfelder:

- `poll_interval_minutes`

Standardwerte:

- Dateimuster: `*.pdf`
- Polling: `15` Minuten
- SMTP-Port: `587`

## Manuelle Ausloesung

Service in Home Assistant:

- `tesla_invoice_automatic.send_latest_invoice`
- `tesla_invoice_automatic.send_historical_invoices`

Optionales Feld:

- `entry_id`
  Wenn gesetzt, wird nur ein bestimmter Konfigurationseintrag aktualisiert.

Zusaetzliche Felder fuer historische Rechnungen:

- `days_back`
  Standard `365`. So weit in die Vergangenheit wird der PDF-Ordner betrachtet.
- `max_invoices`
  Standard `50`. Begrenzt die Anzahl pro Lauf.
- `include_processed`
  Wenn `true`, werden auch bereits bekannte Rechnungen erneut versendet.

## Manueller Schritt

Diese Integration ist die beste realistische kostenlose Loesung. Der Abruf der
offiziellen Tesla-PDF aus Tesla selbst bleibt manuell:

1. Tesla-App oder Tesla-Webbereich oeffnen
2. Offizielle Rechnung als PDF herunterladen
3. PDF in den konfigurierten Watch-Ordner legen

Danach uebernimmt die Integration:

- Erkennen neuer PDFs
- einmaliges Versenden
- Statusspeicherung
- Nachsenden historischer Dateien

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

- `Der Ueberwachungsordner existiert nicht`
  Ordnerpfad in der Integration pruefen.
- `PDF-Datei konnte nicht gelesen werden`
  Datei-Rechte und Dateizustand pruefen.
- `E-Mail mit Tesla-Rechnung konnte nicht gesendet werden`
  SMTP-Host, Port, TLS-Modus und Login pruefen.

Wo nachsehen:

- Home Assistant Logs fuer Laufzeitfehler.
- Sensor-Attribute fuer `last_error`, `last_invoice_id`, `last_email_at`, `last_history_import_at`, `last_history_days`.
- Lokale PDF-Dateien im konfigurierten Watch-Ordner.
- Home Assistant Storage pro Config-Entry fuer bereits verarbeitete Rechnungs-IDs.

Empfohlene Log-Konfiguration in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tesla_invoice_automatic: debug
```

## Security-Hinweise

- Fuer SMTP nach Moeglichkeit ein App-Passwort statt des Hauptpassworts verwenden.
- Logs maskieren keine Geheimnisse automatisch, wenn externe Systeme komplette Requests loggen. Daher Passwoerter nie manuell in Logs kopieren.
- Begrenze Mail-Rechte so stark wie moeglich.

## Troubleshooting

- Wenn keine Rechnung auftaucht, pruefe zuerst, ob die PDF wirklich im richtigen Ordner liegt und auf `.pdf` endet.
- Wenn Rechnungen doppelt verschickt werden, den Storage-Status und die gespeicherten Invoice-IDs kontrollieren.
- Wenn du aeltere Rechnungen brauchst, den Service `tesla_invoice_automatic.send_historical_invoices` mit `days_back` und `max_invoices` ausfuehren.
- Wenn nach Home-Assistant-Neustart nichts mehr geht, Ordnerpfad und SMTP-Verbindung pruefen.

## Lizenz-Hinweis

Das Projekt steht unter der MIT-Lizenz. Details siehe [LICENSE](/Users/joachim.stiegler/TeslaInvoiceAutomatic/LICENSE).
