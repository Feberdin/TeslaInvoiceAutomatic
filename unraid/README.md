# Unraid App Installation

## Ziel

Diese Dateien bereiten den MVP fuer eine app-aehnliche Installation auf Unraid vor.
Im kombinierten Repository liegt der eigentliche Anwendungscode unter `saas/`.

## Was ist enthalten?

- `TeslaInvoiceAutomatic-SaaS.xml`: Docker-Template fuer Unraid
- Single-Container-Laufmodus im Python-Image

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

## Spaeter fuer Community Applications

Wenn die App oeffentlich im App-Store erscheinen soll:

1. XML-Template im GitHub-Repo veroeffentlichen
2. Icon unter `unraid/icon.svg` bereitstellen
3. Image dauerhaft versioniert veroeffentlichen
4. Community Applications Submission vorbereiten
