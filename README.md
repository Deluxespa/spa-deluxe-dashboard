# SPA Deluxe – Marketing Intelligence Dashboard

Automatisiertes, passwortgeschütztes Dashboard für SPA Deluxe. Aggregiert
Zoho-CRM-Deals (Umsatz, Region, Produktkategorie, geschätztes Kundenalter),
Wetterdaten und (sobald Secrets gesetzt sind) Google Ads / Meta Ads / Google
Search Console / Sistrix / Notion zu einem Forecast- und KPI-Dashboard.

Das ausgelieferte `dashboard/index.html` ist **client-seitig AES-256-GCM
verschlüsselt** – ohne das richtige Passwort sieht man nur eine
Passwort-Eingabeseite, keine Klartextdaten. Das Passwort wird nie ins Repo
committet.

## Verzeichnisstruktur

```
lib/       Wiederverwendbare Bausteine (Secrets/Config, Verschlüsselung,
           Forecast-Modell, Wetter-Client)
jobs/      Ausführbare Skripte
  weekly_numbers_update.py   Hauptjob: Daten aktualisieren, Dashboard neu
                              bauen & verschlüsseln (idempotent, cached)
  api_smoke_test.py           Prüft, welche Secrets/Integrationen gesetzt sind
data/
  raw/      Historische Rohdaten-Exporte (Altlast, nicht mehr im Live-Betrieb
            genutzt seit dem Umstieg auf den Zoho-CRM-Live-Pull) – NICHT im Git-Repo
  cache/    Verarbeitete Zwischenstände (processed_rows.json, snapdata.json)
            – NICHT im Git-Repo, wird bei jedem Lauf neu erzeugt
dashboard/
  template/index.html   Unverschlüsselte HTML/JS-Vorlage des Dashboards
  index.html             Verschlüsseltes Ausgabe-Dashboard (wird committet
                          und per GitHub Pages ausgeliefert)
.github/workflows/weekly-update.yml   Wöchentlicher Cronjob (siehe unten)
```

## Lokal einrichten

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env öffnen und mindestens DASHBOARD_PASSWORD setzen
```

`.env` mit den Zoho-CRM-Secrets (`ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`,
`ZOHO_REFRESH_TOKEN`, siehe `.env.example`) füllen – die Deal-Daten werden
dann live per Zoho-API gezogen (kein manueller CSV-Export mehr nötig). Ohne
diese Secrets wird lokal einfach der letzte Cache-Stand aus
`data/cache/processed_rows.json` weiterverwendet, falls vorhanden. Dann:

```bash
python3 jobs/weekly_numbers_update.py
```

Ergebnis:
- `dashboard/index.html` – verschlüsselt, das ist die Datei, die man
  veröffentlicht/deployt
- `dashboard/_local_preview.html` – **unverschlüsselte** Vorschau für lokale
  Kontrolle (im `.gitignore`, nie committen/versenden!)

Zum Ansehen: `dashboard/index.html` im Browser öffnen und `DASHBOARD_PASSWORD`
aus der `.env` eingeben.

Secrets-Status prüfen (zeigt, welche Integrationen noch fehlen, bricht
nichts ab):

```bash
python3 jobs/api_smoke_test.py
```

## Benötigte Secrets (vollständige Liste)

Single Source of Truth ist `lib/config.py` → `SECRET_GROUPS`. Lokal in `.env`
setzen, in GitHub Actions als **Repository Secrets** unter
*Settings → Secrets and variables → Actions*:

| Gruppe | Variablen |
|---|---|
| Dashboard-Verschlüsselung (Pflicht) | `DASHBOARD_PASSWORD` |
| Zoho CRM | `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` (optional: `ZOHO_ACCOUNTS_URL`, `ZOHO_API_DOMAIN`, `ZOHO_WON_STAGES`) |
| Google Ads | `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`, `GOOGLE_ADS_CUSTOMER_ID`, `GOOGLE_ADS_LOGIN_CUSTOMER_ID` |
| Meta Ads | `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_ID` |
| Google Search Console | `GSC_SERVICE_ACCOUNT_JSON`, `GSC_SITE_URL` |
| Sistrix | `SISTRIX_API_KEY`, `SISTRIX_DOMAIN` |
| Notion | `NOTION_TOKEN`, `NOTION_DB_WEEKLY_NUMBERS`, `NOTION_DB_TASKS`, `NOTION_DB_LEARNINGS`, `NOTION_DB_CONTENT_PLAN`, `NOTION_DB_ANOMALIES` |
| Anthropic (KI-Jobs) | `ANTHROPIC_API_KEY` |

Jeder Getter in `lib/config.py` gibt `None` zurück, wenn ein Secret fehlt –
kein Crash. Jobs überspringen die jeweilige Integration dann einfach
graceful und das Dashboard zeigt für den Bereich "keine Daten" statt
abzubrechen. **Nur `DASHBOARD_PASSWORD` ist Pflicht.**

## Wöchentliche Automatisierung (GitHub Actions)

`.github/workflows/weekly-update.yml` läuft jeden Montag 05:00 UTC
(automatisch) und kann zusätzlich manuell über den "Run workflow"-Button im
Actions-Tab gestartet werden. Ablauf:

1. Secrets-Check (informativ)
2. `jobs/weekly_numbers_update.py` ausführen → `dashboard/index.html` neu
   erzeugen
3. Falls sich das Dashboard geändert hat: automatisch committen & pushen
4. `deploy-pages`-Job: baut daraus direkt die GitHub-Pages-Seite (nativer
   `actions/deploy-pages`, kein externes Ziel-Repo nötig)

## Auf einen neuen GitHub bringen

```bash
cd ~/spa-deluxe-automation
git add -A
git commit -m "Initial commit: SPA Deluxe dashboard automation"
git remote add origin https://github.com/<dein-user>/<repo-name>.git
git branch -M main
git push -u origin main
```

Danach im neuen Repo unter *Settings → Secrets and variables → Actions* die
Secrets aus der Tabelle oben eintragen (mindestens `DASHBOARD_PASSWORD`).

Für GitHub Pages: Der `deploy-pages`-Job im Workflow nutzt die native
GitHub-Pages-Integration (`actions/configure-pages` +
`actions/deploy-pages`) direkt auf diesem Repo. Es wird kein zweites Repo
und kein zusätzliches Personal Access Token benötigt – lediglich unter
*Settings → Pages → Build and deployment* die Quelle auf "GitHub Actions"
stellen (einmalig).

## CRM: Zoho statt HubSpot

Seit 2026-08 kommen alle Leads/Deals aus **Zoho CRM** (nicht mehr HubSpot).
Die Deal-Verarbeitung ist in zwei Module aufgeteilt:
- `lib/zoho_processing.py` – Zoho-spezifisch: OAuth2-Refresh-Token-Flow +
  COQL-Abfrage der gewonnenen Deals inkl. verknüpfter Kontaktdaten.
- `lib/deal_processing.py` – CRM-unabhängige Logik (Produktkategorisierung,
  PLZ→Region, Namens-/Altersschätzung), aufrufbar von jedem beliebigen
  CRM-Fetcher über `build_row(...)`.

Die alten HubSpot-Dateien (`jobs/_legacy_build_dashboard.py`,
`lib/hubspot_processing.py`) wurden im Zuge der Migration entfernt. Nur
`lib/name_ages_legacy.py` bleibt als Referenz für die
Namens-/Altersschätzungs-Datenbasis (`NAME_BIRTH_YEAR`) erhalten, die
weiterhin von `lib/deal_processing.py` importiert wird.

## Sicherheit

- `data/raw/`, `data/cache/`, `.env` und `dashboard/_local_preview.html`
  sind in `.gitignore` – dort liegen Klartext-Kundendaten bzw. Secrets.
- `dashboard/index.html` ist das einzige Artefakt mit Kundendaten, das
  committet wird – und das nur in AES-256-GCM-verschlüsselter Form.
- Passwort niemals im Klartext in Commit-Messages, Issues o.ä. posten.
