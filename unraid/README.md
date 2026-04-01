# Unraid App Installation

## Ziel

Diese Dateien bereiten die aktuelle SaaS-Testversion fuer eine app-aehnliche Installation auf Unraid vor.
Im kombinierten Repository liegt der eigentliche Anwendungscode unter `saas/`.

## Was ist enthalten?

- `TeslaInvoiceAutomatic-SaaS.xml`: Docker-Template fuer Unraid
- Single-Container-Laufmodus im Python-Image
- Registrierung, Login und Session-Cookies
- optionaler Google-Login mit demselben Konto fuer Gmail-Versand
- VIN-Verwaltung, Testmail und Rechnungsarchiv
- offizieller Tesla-Fleet-Login fuer Endkunden
- inoffizieller Tesla-Token-Import fuer Self-Hosted-Tests ohne Fleet-Billing
- separates Admin-Menue fuer Betreiber mit Fleet-Public-Key, Partner-Register-Button, Debug-Werkzeugen und Registrierungsuebersicht
- Admin-Cleanup fuer alte Demo-Rechnungen und automatische Live-Betrags-Reparatur
- Demo-Fallback, falls noch kein echter Tesla-Zugang verbunden ist
- Circula als erster einfacher Buchhaltungsversand

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
- Google:
  `ENABLE_GOOGLE_OAUTH`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_SCOPE`, `GOOGLE_OAUTH_REDIRECT_PATH`, `GOOGLE_OAUTH_PROMPT`
- Hintergrundsync:
  `SYNC_INTERVAL_MINUTES` bevorzugt, `SYNC_INTERVAL_SECONDS` nur als Fallback
- Betreiber-Menue:
  `ADMIN_EMAILS`
- Fuer beide Tesla-Varianten:
  `ENABLE_TESLA_FLEET_OAUTH`, `ENABLE_TESLA_OWNER_IMPORT`
- Fuer offiziellen Tesla-Login:
  `TESLA_CLIENT_ID`, `TESLA_CLIENT_SECRET`, `TESLA_FLEET_API_BASE_URL`, `TESLA_PARTNER_TOKEN_SCOPE`
- Fuer echten Mailtest:
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`
- Fuer Circula:
  die eingetragene Mitarbeiter-Adresse wird als sichtbare `Von`-Adresse gesetzt. Dein SMTP-Provider muss diese Absenderadresse zulassen, sonst schreibt er sie eventuell auf das SMTP-Konto um.

## Typischer Testablauf auf Unraid

1. App installieren und starten
2. `/auth` oeffnen
3. Konto registrieren oder `Mit Google anmelden und Gmail freigeben`
4. im Dashboard offiziellen Fleet-Login starten
5. Empfaenger speichern und optional `Circula` aktivieren
6. falls Betreiber: `/admin` oeffnen fuer Testmail-Override, manuelle VINs, Demo-Cleanup und inoffiziellen Token-Import
7. eine VIN pruefen
8. `Testrechnung senden` pruefen
9. falls Betreiber: Fleet-Public-Key erzeugen und Partner-Status pruefen
10. `Fleet-Sync` oder `Demo-Sync` ausloesen
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

## Google-Setup fuer Feberdin

Wenn Google Login und Gmail-Versand denselben Account nutzen sollen:

1. in Google Cloud `gmail.send` aktivieren
2. als Redirect URI exakt `https://tesla-invoice.feberdin.de/oauth/callback` eintragen
3. in Unraid `ENABLE_GOOGLE_OAUTH=true`, `GOOGLE_CLIENT_ID` und `GOOGLE_CLIENT_SECRET` setzen
4. Nutzer melden sich anschliessend auf `/auth` ueber den Google-Button an

Wichtig:

- Gmail wird danach im Versand automatisch vor SMTP bevorzugt.
- Andere sichtbare Absender funktionieren bei Gmail nur, wenn sie im Google-Konto als Alias freigegeben sind.

## Spaeter fuer Community Applications

Wenn die App oeffentlich im App-Store erscheinen soll:

1. XML-Template im GitHub-Repo veroeffentlichen
2. Icon unter `unraid/icon.svg` bereitstellen
3. Image dauerhaft versioniert veroeffentlichen
4. Community Applications Submission vorbereiten
