# SPA Deluxe – Marketing Intelligence Dashboard

Automatisiertes, passwortgeschütztes Dashboard für SPA Deluxe. Aggregiert
Deals (Umsatz, Region, Produktkategorie, geschätztes Kundenalter) aus einem
Google Sheet (befüllt per Zoho-Automatisierung/Zapier/Make), Wetterdaten und
(sobald Secrets gesetzt sind) Google Ads / Meta Ads / Google Search Console /
Sistrix / Notion zu einem Forecast- und KPI-Dashboard.

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
            genutzt seit dem Umstieg auf den Google-Sheets-Live-Pull) – NICHT im Git-Repo
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

`.env` mit den Google-Sheets-Secrets (`GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON`,
`GOOGLE_SHEETS_SPREADSHEET_ID`, siehe `.env.example`) füllen – die Deal-Daten
werden dann live aus dem Google Sheet gezogen (kein manueller CSV-Export mehr
nötig). Ohne diese Secrets wird lokal einfach der letzte Cache-Stand aus
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
| Google Sheets (Deals) | `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEETS_SPREADSHEET_ID` (optional: `GOOGLE_SHEETS_RANGE`, `WON_DEAL_STAGES`) |
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

## CRM: Google Sheet statt HubSpot/Zoho-API

Seit 2026-08 kommen alle Leads/Deals aus **Zoho CRM**, aber nicht mehr per
direkter API-Anbindung: Eine Zoho-Automatisierung (native "Export to Google
Sheets"-Extension oder Zapier/Make) schreibt die gewonnenen Deals in ein
Google Sheet, das dieses Projekt read-only über einen Service Account
ausliest. Die Deal-Verarbeitung ist in zwei Module aufgeteilt:
- `lib/gsheet_processing.py` – Google-Sheets-spezifisch: Service-Account-JWT-
  Auth (kein OAuth2-Refresh-Token nötig) + Auslesen/Parsen der Sheet-Zeilen
  inkl. deutscher Zahlen-/Datumsformate.
- `lib/deal_processing.py` – CRM-unabhängige Logik (Produktkategorisierung,
  PLZ→Region, Namens-/Altersschätzung), aufrufbar von jedem beliebigen
  Fetcher über `build_row(...)`.

**Einrichtung des Google Sheets:**
1. In der Google Cloud Console ein Service Account anlegen und einen JSON-Key
   herunterladen (IAM & Admin → Dienstkonten → Key erstellen).
2. Das Ziel-Sheet mit der `client_email` des Service Accounts teilen
   (Leserechte genügen).
3. Den kompletten Inhalt der JSON-Key-Datei als `GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON`
   und die Spreadsheet-ID (aus der Sheet-URL) als `GOOGLE_SHEETS_SPREADSHEET_ID`
   hinterlegen.
4. Die erste Zeile des Sheets muss erkennbare Spaltennamen enthalten (Deal
   Name/Titel, Amount/Betrag, Closing Date, Stage/Status, First Name/Vorname,
   Last Name/Nachname, Mailing Zip/PLZ/Postleitzahl) – Reihenfolge egal,
   Groß-/Kleinschreibung egal, deutsche und englische Bezeichnungen werden
   erkannt.

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
