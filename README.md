# TeslaInvoiceAutomatic

Home-Assistant-Custom-Integration fuer den automatischen Download offizieller Tesla-Lade-Rechnungen als PDF und den anschliessenden Versand per E-Mail.

## Zweck / Features

- Nutzt eine bestehende [`tesla_ha`](https://github.com/Feberdin/tesla-ha) Anmeldung statt eines kostenpflichtigen Fleet-API-Setups.
- Fragt Teslas mobile Charging-History ab und erkennt neue Rechnungs-PDFs automatisch.
- Laedt offizielle Tesla-Rechnungs-PDFs direkt herunter und speichert sie lokal im Home-Assistant-Konfigurationsordner.
- Versendet neue Rechnungen automatisch per SMTP an eine hinterlegte E-Mail-Adresse.
- Kann aeltere Rechnungen gesammelt nachladen und optional erneut versenden.
- Stellt einen Status-Sensor und zwei manuelle Services in Home Assistant bereit.

## Architektur in Kurzform

- `custom_components/tesla_invoice_automatic/api.py`
  Liest den TeslaPy-Cache aus `tesla_ha`, erneuert Owner-Tokens bei Bedarf und spricht Teslas mobile-app/ownership Endpunkte fuer Ladehistorie und Invoice-PDFs an.
- `custom_components/tesla_invoice_automatic/coordinator.py`
  Pollt die Tesla-Historie, filtert neue bzw. historische Rechnungen, speichert PDFs und startet den Mailversand.
- `custom_components/tesla_invoice_automatic/emailer.py`
  Baut und sendet die SMTP-E-Mail mit PDF-Anhang und klarer Fehlerbehandlung.
- `custom_components/tesla_invoice_automatic/store.py`
  Speichert bereits verarbeitete Tesla-`contentId` Werte persistent, damit Rechnungen nicht doppelt verschickt werden.
- `custom_components/tesla_invoice_automatic/sensor.py`
  Zeigt den letzten Verarbeitungsstatus in Home Assistant an.

## Annahmen

- Home Assistant laeuft mit Custom-Component-Support.
- Die kostenlose Integration [`tesla_ha`](https://github.com/Feberdin/tesla-ha) ist bereits eingerichtet und dein Tesla-Login dort funktioniert.
- Teslas mobile App verwendet weiterhin die heute bekannten Ownership-/Mobile-Endpunkte fuer Charging-History und Invoice-Downloads.
- Ein SMTP-Server ist vorhanden, der PDF-Anhaenge versenden darf.
- Home Assistant darf unter `config/tesla_invoice_automatic/invoices/` Dateien schreiben.

## Quickstart

1. Dieses Repository per HACS oder manuell nach `config/custom_components/tesla_invoice_automatic` in deine Home-Assistant-Umgebung bringen.
2. Sicherstellen, dass [`tesla_ha`](https://github.com/Feberdin/tesla-ha) bereits eingerichtet und mit deinem Tesla verbunden ist.
3. Home Assistant neu starten.
4. In Home Assistant `Einstellungen -> Geraete & Dienste -> Integration hinzufuegen` und nach `Tesla Invoice Automatic` suchen.
5. Deine bestehende `tesla_ha` Verbindung, die VIN und die SMTP-Daten eintragen.
6. Warten, bis nach dem naechsten Ladevorgang eine offizielle Tesla-Rechnung auftaucht oder den Service `tesla_invoice_automatic.send_latest_invoice` ausloesen.

## Konfiguration

Pflichtfelder beim ersten Setup:

- `tesla_ha_entry_id`
- `vin`
- `recipient_email`
- `sender_email`
- `smtp_host`
- `smtp_port`
- `smtp_security`

Optionale Felder:

- `smtp_username`
- `smtp_password`
- `poll_interval_minutes`

Erweiterte Felder im Options-Dialog:

- `device_language`
- `device_country`
- `http_locale`
- `ownership_base_url`

Standardwerte:

- Polling: `15` Minuten
- SMTP-Port: `587`
- App-Sprache: `de`
- App-Land: `DE`
- HTTP-Locale: `de_DE`

## Automatischer Ablauf

1. `tesla_ha` liefert der Integration den vorhandenen Tesla-Login-Cache.
2. Die Integration fragt Teslas Charging-History ueber die Mobile-App-Endpunkte ab.
3. Neue Rechnungen werden ueber ihre Tesla-`contentId` erkannt.
4. Das offizielle PDF wird heruntergeladen und lokal gespeichert.
5. Danach wird die Rechnung per E-Mail verschickt.
6. Erst nach erfolgreichem Speichern und Versenden wird die Rechnung als verarbeitet markiert.

## Historische Rechnungen

Service in Home Assistant:

- `tesla_invoice_automatic.send_historical_invoices`

Wichtige Felder:

- `days_back`
  Standard `365`. So weit in die Vergangenheit wird die Tesla-Ladehistorie beruecksichtigt.
- `max_invoices`
  Standard `50`. Begrenzt die Anzahl pro Lauf.
- `include_processed`
  Wenn `true`, werden bereits bekannte Rechnungen erneut heruntergeladen und versendet.

## So startest du es

Projekt lokal testen:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Syntax-/Importcheck ohne Zusatzpakete:

```bash
python3 -m compileall custom_components tests
```

Optional mit `pytest`, falls du es bereits verwendest:

```bash
pytest -q
```

In Home Assistant:

```bash
cp -R custom_components/tesla_invoice_automatic /pfad/zu/homeassistant/config/custom_components/
```

Oder per HACS als Custom Repository einbinden. Die Datei [hacs.json](/Users/joachim.stiegler/TeslaInvoiceAutomatic/hacs.json) ist vorbereitet.

## So debugst du es

Typische Fehler:

- `Die verknuepfte tesla_ha Integration wurde nicht gefunden`
  `tesla_ha` fehlt oder wurde entfernt.
- `Der tesla_ha Cache wurde nicht gefunden`
  In `tesla_ha` den Tesla-Login erneut abschliessen.
- `Tesla OAuth-Refresh fehlgeschlagen`
  Tesla-Login in `tesla_ha` erneuern und danach Home Assistant neu starten.
- `Tesla Ownership API konnte keinen funktionierenden Endpunkt finden`
  Tesla hat wahrscheinlich einen Mobile-Endpunkt geaendert. Im Log den getesteten Pfad pruefen.
- `E-Mail mit Tesla-Rechnung konnte nicht gesendet werden`
  SMTP-Host, Port, Sicherheitsmodus und Zugangsdaten pruefen.

Wo nachsehen:

- Home Assistant Logs fuer Laufzeitfehler.
- Sensor-Attribute fuer `last_error`, `last_invoice_id`, `last_email_at`, `last_history_import_at`, `last_history_days`, `linked_tesla_ha`.
- Lokale PDF-Dateien unter `config/tesla_invoice_automatic/invoices/`.
- Home Assistant Storage pro Config-Entry fuer bereits verarbeitete Rechnungs-IDs.

Empfohlene Log-Konfiguration in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tesla_invoice_automatic: debug
```

## Troubleshooting

- Wenn keine Rechnung auftaucht, pruefe zuerst in der Tesla-App, ob fuer den Ladevorgang wirklich eine Rechnung verfuegbar ist.
- Wenn Rechnungen doppelt verschickt werden, den Storage-Status und die gespeicherten `contentId` Werte kontrollieren.
- Wenn du aeltere Rechnungen brauchst, den Service `tesla_invoice_automatic.send_historical_invoices` mit `days_back` und `max_invoices` ausfuehren.
- Wenn nach Tesla- oder Home-Assistant-Updates etwas bricht, im Log auf HTTP-Status, getestete Basis-URL und Antwort-Auszug achten.

## Security-Hinweise

- Fuer SMTP nach Moeglichkeit ein App-Passwort statt des Hauptpassworts verwenden.
- Die Integration nutzt den vorhandenen TeslaPy-Cache aus `tesla_ha`. Diesen Cache nicht manuell weitergeben oder in Tickets posten.
- Logs enthalten absichtlich keine kompletten Tokens oder Passwoerter.
- Begrenze Mail-Rechte so stark wie moeglich.

## Bekannte Grenzen

- Die verwendeten Tesla-Mobile-Endpunkte sind nicht Teil der offiziellen Fleet-API-Dokumentation und koennen sich ohne Vorankuendigung aendern.
- Ohne verfuegbare Rechnung in Teslas Ladehistorie kann auch diese Integration keine PDF erzeugen oder nachbauen.
- Der Abruf klappt nur, solange `tesla_ha` gueltige Tesla-Owner-Tokens besitzt.

## Lizenz-Hinweis

Das Projekt steht unter der MIT-Lizenz. Details siehe [LICENSE](/Users/joachim.stiegler/TeslaInvoiceAutomatic/LICENSE).
