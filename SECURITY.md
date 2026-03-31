# Security Policy

## Supported Versions

Es wird jeweils nur die neueste GitHub-Release-Version aktiv gepflegt.

## Was dieses Projekt speichert

- SMTP-Konfiguration in Home Assistant
- Lokale Tesla-Rechnungs-PDFs unter `config/tesla_invoice_automatic/invoices/`
- Tesla-Invoice-Status und Versandzaehler in Home Assistants `.storage`
- Einen von `tesla_ha` bereitgestellten TeslaPy-Cache

## Wichtige Sicherheitshinweise

- Nutze fuer SMTP nach Moeglichkeit ein App-Passwort.
- Poste niemals deinen `tesla_ha` Cache, Tesla-Tokens, SMTP-Passwoerter oder komplette Home-Assistant-Logs mit Secrets in Issues.
- Wenn du ein Problem meldest, entferne VIN, E-Mail-Adressen, Dateipfade und Tesla-Antworten mit sensiblen Inhalten.
- Begrenze Dateizugriff und Mail-Rechte deines Home-Assistant-Hosts moeglichst stark.

## Sicherheitsprobleme melden

Bitte keine oeffentlichen Issues fuer echte Sicherheitsluecken mit Secrets oder reproduzierbaren Zugangsdaten anlegen.

Stattdessen:

1. Beschreibe das Problem zunaechst knapp und ohne Geheimnisse.
2. Erklaere, welche Version betroffen ist.
3. Lege nur sichere, bereinigte Logs oder Screenshots bei.

Wenn du unsicher bist, reduziere die Informationen lieber zu stark als zu wenig.
