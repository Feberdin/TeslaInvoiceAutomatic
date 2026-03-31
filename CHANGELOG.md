# Changelog

Alle nennenswerten Aenderungen an `Tesla Invoice Automatic` werden hier kurz dokumentiert.

## v0.5.3

- GitHub-Community-Dateien vervollstaendigt: `CODE_OF_CONDUCT.md` und Pull-Request-Template hinzugefuegt.
- README und `CONTRIBUTING.md` um direkte Verweise auf Zusammenarbeit, Sicherheit und Pull-Requests erweitert.
- Repo-Metadaten fuer GitHub aufbereitet, damit Beschreibung und Projektkontext klarer sichtbar sind.

## v0.5.2

- Options-Flow auf das aktuelle Home-Assistant-Muster mit `OptionsFlowWithReload` umgestellt.
- Entfernt das alte manuelle Setzen von `self.config_entry`, das auf neueren Home-Assistant-Versionen den Einstellungsdialog stoeren kann.
- Neuer `Reconfigure`-Pfad fuer den `Konfigurieren`-Dialog in Home Assistant.
- Entfernt widerspruechliche Alt-Werte aus `options`, damit neu gespeicherte Basisdaten nicht verdeckt werden.
- Ziel: den 500-Fehler beim Oeffnen oder Aendern der Integrationseinstellungen beheben.

## v0.5.1

- Options- und Einstellungsdialog gegen fehlende oder nicht mehr verfuegbare `tesla_ha` Eintraege gehaertet.
- Verhindert einen serverseitigen 500-Fehler beim Oeffnen der Integrationseinstellungen in Home Assistant.

## v0.5.0

- Neue Status- und Statistik-Sensoren fuer Abruf, Versand, Fehlerfolgen und Monatszaehler.
- Bestehender Status-Sensor zeigt jetzt den letzten echten Abrufstatus statt nur den letzten Versand.
- README deutlich erweitert: Installation, Entitaeten, Services, Troubleshooting, HACS- und GitHub-Hinweise.
- GitHub-Supportdateien ergaenzt: Security-Hinweis und Issue-Templates.
- HACS-Metadaten verbessert.

## v0.4.0

- Automatischer Download offizieller Tesla-Lade-Rechnungen ueber bestehende `tesla_ha` Anmeldung.
- Tesla-Mobile-/Ownership-Endpunkte statt Fleet API.
- Historischer Rechnungsimport und SMTP-Versand.

## v0.3.0

- Uebergangsloesung fuer lokale PDF-Ueberwachung.

## v0.2.0

- Frueher Versuch der Anbindung an bestehende Tesla-Anmeldung.

## v0.1.1

- Erstes veröffentlichtes Grundgeruest.
