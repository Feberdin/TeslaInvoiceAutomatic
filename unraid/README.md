# Unraid App Installation

## Ziel

Diese Dateien bereiten die aktuelle SaaS-Testversion fuer eine app-aehnliche Installation auf Unraid vor.
Im kombinierten Repository liegt der eigentliche Anwendungscode unter `saas/`.

## Was ist enthalten?

- `TeslaInvoiceAutomatic-SaaS.xml`: Docker-Template fuer Unraid
- Single-Container-Laufmodus im Python-Image
- Registrierung, Login und Session-Cookies
- VIN-Verwaltung, Testmail und Rechnungsarchiv
- offizieller Tesla-Fleet-Login fuer Endkunden
- inoffizieller Tesla-Token-Import fuer Self-Hosted-Tests ohne Fleet-Billing
- separates Admin-Menue fuer Betreiber mit Fleet-Public-Key und Partner-Register-Button
- Demo-Fallback, falls noch kein echter Tesla-Zugang verbunden ist
- bevorzugter Live-Weg, falls beide Varianten gespeichert sind

## Wichtiger Hinweis

Damit die App in Unraid installierbar ist, muss das Docker-Image zuerst in eine Registry veroeffentlicht werden, zum Beispiel:

- `ghcr.io/feberdin/tesla-invoice-automatic-saas:latest`

Ohne veroeffentlichtes Image kann Unraid zwar das Template sehen, aber den Container nicht herunterladen.

## Schnelltest als User Template

1. Docker-Image nach GHCR oder Docker Hub pushen.
2. Die XML-Datei nach Unraid kopieren:

```text
/boot/config/plugins/dockerMan/templates-user/TeslaInvoiceAutomatic-SaaS.xml
```

3. Docker-Service in Unraid neu laden oder die Docker-Seite aktualisieren.
4. Die App als User Template installieren.

## Empfohlene Unraid-Werte

- Port:
  `8010 -> 8000`, falls `8000` bereits belegt ist
- Persistenter Pfad:
  `/mnt/cache/appdata/tesla-invoice-automatic-saas -> /data`
- Pflichtvariablen:
  `APP_BASE_URL`, `SECRET_KEY`, `DATABASE_URL`, `DATA_DIR`, `DEMO_MODE`, `DEFAULT_FROM_EMAIL`
- Betreiber-Menue:
  `ADMIN_EMAILS`
- Fuer beide Tesla-Varianten:
  `ENABLE_TESLA_FLEET_OAUTH`, `ENABLE_TESLA_OWNER_IMPORT`
- Fuer offiziellen Tesla-Login:
  `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET`, `TESLA_FLEET_API_BASE_URL`, `TESLA_PARTNER_TOKEN_SCOPE`
- Fuer echten Mailtest:
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`

## Typischer Testablauf auf Unraid

1. App installieren und starten
2. `/auth` oeffnen
3. Konto registrieren
4. im Dashboard offiziellen Fleet-Login oder inoffiziellen Token-Import waehlen
5. eine VIN hinterlegen
6. optional den bevorzugten Live-Weg speichern
7. Empfaenger speichern
8. `Testrechnung senden` pruefen
9. falls Betreiber: `/admin` oeffnen, Fleet-Public-Key erzeugen und Partner-Status pruefen
10. `Fleet-Sync`, `Token-Sync` oder `Demo-Sync` ausloesen
11. Logs, PDFs und `email-outbox.log` kontrollieren

## Debug-Hinweise

- Container-Logs:
  im Unraid-Docker-Tab
- Rechnungen:
  `/mnt/cache/appdata/tesla-invoice-automatic-saas/invoices`
- Mail-Outbox:
  `/mnt/cache/appdata/tesla-invoice-automatic-saas/email-outbox.log`
- SQLite:
  `/mnt/cache/appdata/tesla-invoice-automatic-saas/local_demo.db`

## Spaeter fuer Community Applications

Wenn die App oeffentlich im App-Store erscheinen soll:

1. XML-Template im GitHub-Repo veroeffentlichen
2. Icon unter `unraid/icon.svg` bereitstellen
3. Image dauerhaft versioniert veroeffentlichen
4. Community Applications Submission vorbereiten
