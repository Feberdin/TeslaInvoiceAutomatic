# TeslaInvoiceAutomatic

[![GitHub Release](https://img.shields.io/github/v/release/Feberdin/TeslaInvoiceAutomatic?sort=semver)](https://github.com/Feberdin/TeslaInvoiceAutomatic/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Tests](https://github.com/Feberdin/TeslaInvoiceAutomatic/actions/workflows/tests.yml/badge.svg)](https://github.com/Feberdin/TeslaInvoiceAutomatic/actions/workflows/tests.yml)

Home-Assistant-Custom-Integration fuer den automatischen Download offizieller Tesla-Lade-Rechnungen als PDF und den anschliessenden Versand per E-Mail.

## Community Und Zusammenarbeit

Wenn du das Projekt nutzen oder erweitern willst, sind diese Dateien der beste Start:

- [CONTRIBUTING.md](CONTRIBUTING.md)
  Entwicklungsablauf, lokale Tests und Stilregeln.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
  Erwarteter respektvoller Umgang bei Issues, Pull Requests und Diskussionen.
- [SECURITY.md](SECURITY.md)
  Wie Sicherheitsprobleme verantwortungsvoll gemeldet werden sollen.
- [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md)
  Checkliste fuer nachvollziehbare Aenderungen.

## Installation in Home Assistant

Diese Anleitung ist absichtlich sehr konkret geschrieben, damit du die
Integration direkt in Home Assistant einrichten kannst, ohne die restliche
README vorher komplett lesen zu muessen.

### Voraussetzungen

Bevor du startest, sollte Folgendes bereits vorhanden sein:

- Ein laufender Home-Assistant-Server
- HACS oder alternativ Zugriff auf den Ordner `config/custom_components/`
- Eine funktionierende [`tesla_ha`](https://github.com/Feberdin/tesla-ha) Integration
- Ein SMTP-Postfach oder SMTP-Relay fuer den Mailversand
- Deine Tesla-VIN

Wichtig:

- Diese Integration baut auf deiner vorhandenen `tesla_ha` Anmeldung auf.
- Du musst hier **keine** Fleet API einrichten.
- Ohne funktionierende `tesla_ha` Verbindung kann diese Integration keine Rechnungen laden.

### Schritt 1: `tesla_ha` zuerst einrichten

Wenn `tesla_ha` noch nicht installiert ist:

1. Das Repo [`Feberdin/tesla-ha`](https://github.com/Feberdin/tesla-ha) installieren.
2. Home Assistant neu starten.
3. Die Integration `tesla_ha` hinzufügen.
4. Den Tesla-Login dort vollständig abschließen.
5. Prüfen, ob dein Tesla in Home Assistant bereits sichtbar ist.

Erst wenn das funktioniert, solltest du `Tesla Invoice Automatic` einrichten.

### Schritt 2: Diese Integration über HACS installieren

Empfohlener Weg:

1. HACS öffnen.
2. Oben rechts auf die drei Punkte gehen.
3. `Custom repositories` öffnen.
4. Als URL eintragen:

   `https://github.com/Feberdin/TeslaInvoiceAutomatic`

5. Als Typ `Integration` auswählen.
6. Repository hinzufügen.
7. Danach in HACS nach `Tesla Invoice Automatic` suchen.
8. Die Integration installieren.
9. Home Assistant neu starten.

### Schritt 3: Alternative manuelle Installation

Falls du HACS nicht nutzen willst:

1. Dieses Repository herunterladen oder klonen.
2. Den Ordner `custom_components/tesla_invoice_automatic` in deinen Home-Assistant-Konfigurationsordner kopieren:

```bash
cp -R custom_components/tesla_invoice_automatic /pfad/zu/homeassistant/config/custom_components/
```

3. Home Assistant neu starten.

### Schritt 4: Integration in Home Assistant hinzufügen

Nach dem Neustart:

1. In Home Assistant `Einstellungen -> Geräte & Dienste` öffnen.
2. Auf `Integration hinzufügen` klicken.
3. Nach `Tesla Invoice Automatic` suchen.
4. Die Integration auswählen.

Im Einrichtungsdialog trägst du ein:

- die bestehende `tesla_ha` Verbindung
- deine `Tesla VIN`
- `recipient_email`
- `sender_email`
- `smtp_host`
- `smtp_port`
- optional `smtp_username`
- optional `smtp_password`
- `smtp_security`
- optional `poll_interval_minutes`

### Schritt 5: Erster Funktionstest

Nach der Einrichtung:

1. Prüfen, ob die Sensoren der Integration angelegt wurden.
2. Den Service `tesla_invoice_automatic.send_latest_invoice` einmal manuell ausführen.
3. Danach die Sensoren prüfen, vor allem:
   - `Status`
   - `Last Successful Fetch`
   - `Consecutive Failures`
   - `Last Invoice Sent`
4. Zusätzlich im Home-Assistant-Dateisystem prüfen, ob PDFs unter
   `config/tesla_invoice_automatic/invoices/` auftauchen.

### Schritt 6: Historische Rechnungen importieren

Wenn du ältere Rechnungen ebenfalls brauchst:

1. In `Entwicklerwerkzeuge -> Aktionen` gehen.
2. Den Service `tesla_invoice_automatic.send_historical_invoices` wählen.
3. Zum Beispiel diese Werte setzen:

```yaml
days_back: 365
max_invoices: 50
include_processed: false
```

4. Service ausführen.
5. Danach `Pending Invoices`, `Invoices Sent Total` und `Last Run Processed Invoices` prüfen.

### Wenn etwas nicht funktioniert

Die häufigsten Ursachen sind:

- `tesla_ha` ist nicht mehr eingeloggt
- SMTP-Zugangsdaten sind falsch
- Tesla stellt für den Ladevorgang noch keine Rechnung bereit
- ein Tesla-Mobile-Endpunkt hat sich geändert

Dann zuerst prüfen:

1. Home-Assistant-Logs
2. den `Status`-Sensor
3. `Consecutive Failures`
4. `last_error` im Status-Sensor
5. ob `tesla_ha` selbst noch korrekt funktioniert

## Zweck / Features

- Nutzt eine bestehende [`tesla_ha`](https://github.com/Feberdin/tesla-ha) Anmeldung statt eines kostenpflichtigen Fleet-API-Setups.
- Fragt Teslas mobile Charging-History ab und erkennt neue Rechnungs-PDFs automatisch.
- Laedt offizielle Tesla-Rechnungs-PDFs direkt herunter und speichert sie lokal im Home-Assistant-Konfigurationsordner.
- Versendet neue Rechnungen automatisch per SMTP an eine hinterlegte E-Mail-Adresse.
- Kann aeltere Rechnungen gesammelt nachladen und optional erneut versenden.
- Stellt einen Status-Sensor plus mehrere Statistik- und Diagnose-Sensoren in Home Assistant bereit.

## Architektur in Kurzform

- `custom_components/tesla_invoice_automatic/api.py`
  Liest den TeslaPy-Cache aus `tesla_ha`, erneuert Owner-Tokens bei Bedarf und spricht Teslas mobile-app/ownership Endpunkte fuer Ladehistorie und Invoice-PDFs an.
- `custom_components/tesla_invoice_automatic/coordinator.py`
  Pollt die Tesla-Historie, filtert neue bzw. historische Rechnungen, speichert PDFs, startet den Mailversand und pflegt Statuszaehler.
- `custom_components/tesla_invoice_automatic/emailer.py`
  Baut und sendet die SMTP-E-Mail mit PDF-Anhang und klarer Fehlerbehandlung.
- `custom_components/tesla_invoice_automatic/store.py`
  Speichert bereits verarbeitete Tesla-`contentId` Werte sowie Versand- und Fehlerstatistiken persistent.
- `custom_components/tesla_invoice_automatic/sensor.py`
  Exponiert Status-, Zeitstempel- und Zaehler-Sensoren fuer Dashboards und Automationen.

## Annahmen

- Home Assistant laeuft mit Custom-Component-Support.
- Die kostenlose Integration [`tesla_ha`](https://github.com/Feberdin/tesla-ha) ist bereits eingerichtet und dein Tesla-Login dort funktioniert.
- Teslas mobile App verwendet weiterhin die heute bekannten Ownership-/Mobile-Endpunkte fuer Charging-History und Invoice-Downloads.
- Ein SMTP-Server ist vorhanden, der PDF-Anhaenge versenden darf.
- Home Assistant darf unter `config/tesla_invoice_automatic/invoices/` Dateien schreiben.

## Quickstart

1. Sicherstellen, dass [`tesla_ha`](https://github.com/Feberdin/tesla-ha) bereits eingerichtet und mit deinem Tesla verbunden ist.
2. Dieses Repository per HACS oder manuell nach `config/custom_components/tesla_invoice_automatic` in deine Home-Assistant-Umgebung bringen.
3. Home Assistant neu starten.
4. In Home Assistant `Einstellungen -> Geraete & Dienste -> Integration hinzufuegen` und nach `Tesla Invoice Automatic` suchen.
5. Deine bestehende `tesla_ha` Verbindung, die VIN und die SMTP-Daten eintragen.
6. Warten, bis nach dem naechsten Ladevorgang eine offizielle Tesla-Rechnung auftaucht oder den Service `tesla_invoice_automatic.send_latest_invoice` ausloesen.

## Installation ueber HACS

1. HACS oeffnen.
2. `Custom repositories` aufrufen.
3. `https://github.com/Feberdin/TeslaInvoiceAutomatic` als Repository vom Typ `Integration` hinzufuegen.
4. `Tesla Invoice Automatic` installieren.
5. Home Assistant neu starten.

## Manuelle Installation

```bash
cp -R custom_components/tesla_invoice_automatic /pfad/zu/homeassistant/config/custom_components/
```

Danach Home Assistant neu starten und die Integration ueber die UI einrichten.

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

## Entitaeten

Die Integration erzeugt standardmaessig diese Sensoren:

- `Status`
  Letzter Abrufstatus. Typische Werte: `idle`, `no_new_invoices`, `sent`, `error`.
- `Last Successful Fetch`
  Zeitpunkt des letzten erfolgreichen Tesla-Abrufs.
- `Last Invoice Sent`
  Zeitpunkt, zu dem zuletzt erfolgreich eine Rechnung per Mail verschickt wurde.
- `Pending Invoices`
  Wie viele gefundene Rechnungen nach dem letzten Lauf noch offen sind.
- `Invoices Sent Total`
  Gesamtzahl aller erfolgreich versendeten Rechnungen.
- `Invoices Sent This Month`
  Anzahl der in diesem Kalendermonat versendeten Rechnungen.
- `Consecutive Failures`
  Wie viele Fehlerlaeufe direkt hintereinander aufgetreten sind.
- `Last Fetch Duration`
  Dauer des letzten Abrufs inklusive Download und Versand.
- `Last Run Processed Invoices`
  Wie viele Rechnungen im letzten Lauf verarbeitet wurden.

## Sensoren Im Dashboard

Fuer ein Home-Assistant-Dashboard sind diese Sensoren meist am hilfreichsten:

- `Invoices Sent This Month`
  Schneller Monatszaehler fuer Abrechnungen.
- `Invoices Sent Total`
  Gesamtzahl aller erfolgreichen Rechnungsversendungen.
- `Pending Invoices`
  Zeigt, ob nach einem Lauf oder historischen Import noch Rechnungen offen sind.
- `Status`
  Der wichtigste Uebersichts-Sensor. Typische Werte sind `sent`, `no_new_invoices` oder `error`.
- `Consecutive Failures`
  Gut fuer Warnungen, wenn Tesla- oder SMTP-Abrufe mehrfach hintereinander scheitern.
- `Last Fetch Duration`
  Hilft, auffaellig langsame Abrufe zu erkennen.
- `Last Invoice Sent`
  Bestaetigt, wann zuletzt erfolgreich eine Rechnung verschickt wurde.
- `Last Successful Fetch`
  Zeigt, wann Tesla zuletzt erfolgreich abgefragt wurde.
- `Last Run Processed Invoices`
  Besonders praktisch nach `send_historical_invoices`.

Wichtige Attribute am `Status`-Sensor:

- `last_error`
- `last_fetch_attempt_at`
- `last_successful_fetch_at`
- `last_invoice_id`
- `last_session_id`
- `last_downloaded_file`
- `last_run_status`
- `last_run_processed_count`
- `invoices_sent_total`
- `invoices_sent_this_month`
- `consecutive_failures`
- `linked_tesla_ha`

## Sinnvolle Automationen

- Benachrichtige dich, wenn `Consecutive Failures > 0` oder `Status = error`.
- Erstelle eine Monatskarte mit `Invoices Sent This Month`.
- Zeige `Last Successful Fetch` und `Last Invoice Sent` im Fahrzeug- oder Arbeitgeber-Dashboard an.
- Nutze `Pending Invoices`, um nach einem historischen Import zu erkennen, ob noch etwas offen ist.

## Services

Verfuegbare Services:

- `tesla_invoice_automatic.send_latest_invoice`
  Startet sofort eine neue Tesla-Abfrage.
- `tesla_invoice_automatic.send_historical_invoices`
  Holt historische Rechnungen erneut oder gesammelt nach.

Wichtige Felder fuer `send_historical_invoices`:

- `days_back`
  Standard `365`. So weit in die Vergangenheit wird die Tesla-Ladehistorie beruecksichtigt.
- `max_invoices`
  Standard `50`. Begrenzt die Anzahl pro Lauf.
- `include_processed`
  Wenn `true`, werden bereits bekannte Rechnungen erneut heruntergeladen und versendet.

## Upgrade-Hinweise

- Wenn du aus einer alten Zwischenversion kommst, entferne den alten Config-Entry und richte die Integration neu ein.
- `v0.5.1` haertet den Einstellungsdialog gegen fehlende oder nicht mehr verfuegbare `tesla_ha` Verknuepfungen.
- `v0.5.2` stellt den Options-Flow auf das aktuelle Home-Assistant-Muster um und fuegt einen echten `Konfigurieren`-Pfad fuer neuere Home-Assistant-Versionen hinzu.
- `v0.5.3` ergaenzt GitHub-Community-Dateien und Repo-Metadaten. Fuer Home Assistant ist kein Neu-Einrichten noetig.
- Nach Release-Updates in HACS am besten:
  1. Update installieren
  2. Home Assistant neu starten
  3. Sensorzustand pruefen

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
- `Der Konfigurationsfluss konnte nicht geladen werden: 500 Internal Server Error`
  Sicherstellen, dass mindestens `v0.5.2` installiert ist, danach Home Assistant komplett neu starten und die Integration ueber `Konfigurieren` oder `Optionen` erneut oeffnen.

Wo nachsehen:

- Home Assistant Logs fuer Laufzeitfehler.
- Sensorwerte fuer `Status`, `Last Successful Fetch`, `Consecutive Failures` und `Invoices Sent Total`.
- Sensorattribute fuer `last_error`, `last_invoice_id`, `last_downloaded_file`, `linked_tesla_ha`.
- Lokale PDF-Dateien unter `config/tesla_invoice_automatic/invoices/`.
- Home Assistant Storage pro Config-Entry fuer bereits verarbeitete Rechnungs-IDs und Zaehler.

Empfohlene Log-Konfiguration in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tesla_invoice_automatic: debug
```

## Troubleshooting

- Wenn keine Rechnung auftaucht, pruefe zuerst in der Tesla-App, ob fuer den Ladevorgang wirklich eine Rechnung verfuegbar ist.
- Wenn `Last Successful Fetch` alt ist und `Consecutive Failures` steigt, ist meist der `tesla_ha` Login oder ein Tesla-Endpunkt das Problem.
- Wenn Rechnungen doppelt verschickt werden, den Storage-Status und die gespeicherten `contentId` Werte kontrollieren.
- Wenn du aeltere Rechnungen brauchst, den Service `tesla_invoice_automatic.send_historical_invoices` mit `days_back` und `max_invoices` ausfuehren.
- Wenn nach Tesla- oder Home-Assistant-Updates etwas bricht, im Log auf HTTP-Status, getestete Basis-URL und Antwort-Auszug achten.

## GitHub / Support

- Releases: [GitHub Releases](https://github.com/Feberdin/TeslaInvoiceAutomatic/releases)
- Changelog: [CHANGELOG.md](/Users/joachim.stiegler/TeslaInvoiceAutomatic/CHANGELOG.md)
- Security: [SECURITY.md](/Users/joachim.stiegler/TeslaInvoiceAutomatic/SECURITY.md)
- Fehler und Feature-Wuensche bitte ueber die Issue-Templates melden.

Wenn du ein Issue erstellst, hilf am meisten mit:

- Release-Version
- Home-Assistant-Version
- `tesla_ha` Version
- bereinigten Logs
- relevanten Sensorwerten

## HACS / Repository-Hinweise

- Das Repo ist als HACS Custom Repository vorgesehen.
- `hacs.json` ist auf die Integrations-Domain ausgerichtet.
- Das README ist fuer HACS-Rendering geschrieben.
- Releases werden getaggt, damit Updates in HACS klar nachvollziehbar sind.

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
