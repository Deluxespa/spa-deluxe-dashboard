"""
Zoho-CRM-Export-Anbindung ueber Google Drive (siehe Chat-Historie 2026-08-20).

Der Nutzer laedt woechentlich (typischerweise montags) neue CSV-Exporte aus
Zoho in den Google-Drive-Ordner "Zoho CRM Exporte" hoch. Es gibt 3 Dateitypen,
jeweils am Dateinamen-Praefix + Datum erkennbar:

  - Top_Tier_Anzahl_<Datum>.csv   -> Lead-Zaehlung "Top Tier"-Quellen
  - SM_Leads_Anzahl_<Datum>.csv   -> Lead-Zaehlung Social-Media-Quellen
  - Abschluesse_<Datum>.csv       -> abgeschlossene Deals des Monats

Format-Eigenheiten dieser Zoho-Exporte (nicht unser Design, muessen wir so
hinnehmen):
  1) Zeilenumbrueche sind KEINE echten Newline-Bytes, sondern der woertliche
     2-Zeichen-String "\\n" im Text (Zoho-Export-Bug/-Eigenart). Wir splitten
     deshalb explizit auf diesen String (und zur Sicherheit auch auf echte
     Newlines, falls Zoho das mal repariert).
  2) Trennzeichen ist ";" (Semikolon).
  3) Top_Tier/SM_Leads-Dateien sind "Pivot"-Tabellen: jede ZEILE ist ein Feld
     (Tag / Quelle / Gesamtanzahl), jede SPALTE ab Spalte 2 ist eine
     Lead-Quelle mit ihrer Anzahl. Letzte Spalte = "GESAMT" (Summe).
  4) Die Abschluesse-Datei ist TRANSPONIERT: jede ZEILE ist ein Feld
     (Vorname / PLZ / Produkt / Betrag / Abschlussdatum / Deal-Name), jede
     SPALTE ab Spalte 2 ist EIN einzelner Deal. Bei vielen Deals (>25) laufen
     die Excel-Spaltenbuchstaben ueber Z hinaus nach AA, AB, AC, ... - das ist
     rein kosmetisch (Excel-Spaltennotation), wir parsen ueber Semikolon-Split
     und nicht ueber Spaltenbuchstaben, daher ist das fuer uns irrelevant.
     Die letzte Spalte jeder Abschluesse-Datei ist eine Summen-/Total-Spalte
     (erkennbar an "GESAMT" im Deal-Name-Feld bzw. "ANZAHL n" im Produkt-Feld)
     und wird beim Parsen verworfen, da sie kein echter Einzel-Deal ist.

Dieses Modul ist bewusst unabhaengig von lib/gsheet_processing.py gehalten
(eigene, minimale JWT-Auth gegen die Drive-API mit dem gleichen
Google-Service-Account wie fuer Sheets), verwendet aber fuer die eigentliche
Deal-Verarbeitung dieselbe zentrale, CRM-unabhaengige Logik wie die anderen
Quellen: lib/deal_processing.build_row (siehe dort).
"""
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from lib import config
from lib import deal_processing

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"

# Ordner "Zoho CRM Exporte" in Google Drive (kann per ENV ueberschrieben werden).
ZOHO_DRIVE_FOLDER_ID_DEFAULT = "1OHLAE9LAp58vbB6Vl6sob0PzBAWcoek9"

FILE_TYPE_PATTERNS = {
    "top_tier": re.compile(r"^Top_Tier", re.IGNORECASE),
    "sm_leads": re.compile(r"^SM_Leads", re.IGNORECASE),
    "abschluesse": re.compile(r"^Abschluesse", re.IGNORECASE),
}


def _folder_id() -> str:
    return config.get("ZOHO_DRIVE_FOLDER_ID", ZOHO_DRIVE_FOLDER_ID_DEFAULT)


# ---- Google-Auth (Service-Account-JWT, gleiche Credentials wie Sheets) ----

def _load_service_account() -> dict:
    raw = config.require("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    return json.loads(raw)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _get_access_token(scope: str = DRIVE_SCOPE) -> str:
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15

    sa = _load_service_account()
    token_uri = sa.get("token_uri") or TOKEN_URI_DEFAULT
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": scope,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        f"{_b64url(json.dumps(header).encode())}."
        f"{_b64url(json.dumps(claims).encode())}"
    )
    key = RSA.import_key(sa["private_key"])
    digest = SHA256.new(signing_input.encode("ascii"))
    signature = pkcs1_15.new(key).sign(digest)
    jwt = f"{signing_input}.{_b64url(signature)}"

    body = (
        "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
        f"&assertion={jwt}"
    ).encode("ascii")
    req = urllib.request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Google-OAuth (Drive): kein access_token in Antwort: {data}")
    return token


# ---- Drive-API: Ordnerinhalt listen / Datei herunterladen ----

def list_folder_files(folder_id: Optional[str] = None, access_token: Optional[str] = None) -> list:
    """Listet alle nicht-geloeschten Dateien im Ordner, neueste zuerst (modifiedTime desc)."""
    folder_id = folder_id or _folder_id()
    if access_token is None:
        access_token = _get_access_token()
    q = f"'{folder_id}' in parents and trashed = false"
    url = (
        "https://www.googleapis.com/drive/v3/files"
        f"?q={urllib.parse.quote(q)}"
        f"&fields={urllib.parse.quote('files(id,name,modifiedTime,mimeType)')}"
        f"&orderBy={urllib.parse.quote('modifiedTime desc')}&pageSize=100"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("files", [])


def pick_latest_per_type(files: list) -> dict:
    """Waehlt pro Dateityp (top_tier / sm_leads / abschluesse) jeweils die
    zuletzt geaenderte Datei aus. Das entspricht genau 'die neuesten 3
    Dateien' des Nutzers, wenn jede Woche eine neue Datei pro Typ hochgeladen
    wird."""
    best = {}
    for f in files:
        name = f.get("name", "")
        for ftype, pattern in FILE_TYPE_PATTERNS.items():
            if pattern.match(name):
                cur = best.get(ftype)
                if cur is None or f.get("modifiedTime", "") > cur.get("modifiedTime", ""):
                    best[ftype] = f
    return best


def download_file_text(file_id: str, access_token: Optional[str] = None) -> str:
    if access_token is None:
        access_token = _get_access_token()
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return raw.decode("utf-8-sig")


# ---- Parsing ----

def _split_rows(text: str) -> list:
    """Zoho-Eigenheit: Zeilenumbrueche sind der woertliche String '\\n' statt
    echter Newline-Bytes. Wir normalisieren auf echte Newlines und splitten."""
    text = text.replace("\r\n", "\n").replace("\\n", "\n")
    return [line for line in text.split("\n") if line != ""]


def _split_cells(row: str) -> list:
    return row.split(";")


def parse_pivot_counts(text: str) -> dict:
    """Parst Top_Tier_*/SM_Leads_*-Dateien (Pivot: Zeile=Feld, Spalte=Quelle).
    Rueckgabe: {"date": "YYYY-MM-DD"|None, "sources": [{"quelle","anzahl"}, ...],
    "gesamt": int|None, "warning": str|None}.

    Praxis-Eigenheit: bei manchen echten Zoho-Exporten hat die 'Quelle'-Zeile
    eine andere Spaltenanzahl als die 'Gesamtanzahl'-Zeile (es fehlt dann
    irgendwo mittendrin ein Zahlenwert - ein Datenfehler im Zoho-Export
    selbst, keine Newline/Trennzeichen-Frage). Da die letzte Spalte in beiden
    Zeilen zuverlaessig 'GESAMT' bzw. die Gesamtsumme ist, richten wir bei
    Laengen-Mismatch RECHTSBUENDIG aus (von hinten her paaren), damit
    zumindest GESAMT sicher korrekt erkannt wird. Ueberzaehlige Eintraege am
    Anfang der laengeren Zeile koennen dann keinem Zahlenwert zugeordnet
    werden und werden mit anzahl=None ausgegeben (statt falsch verschoben zu
    werden) + eine "warning" wird gesetzt."""
    rows = _split_rows(text)
    field = {}
    for row in rows:
        cells = _split_cells(row)
        if not cells:
            continue
        field[cells[0].strip()] = cells[1:]

    tag_row = field.get("Tag", [])
    quelle_row = field.get("Quelle", [])
    anzahl_row = field.get("Gesamtanzahl", [])
    date = tag_row[0].strip() if tag_row else None

    warning = None
    if len(quelle_row) != len(anzahl_row):
        warning = (
            f"Spaltenanzahl von 'Quelle' ({len(quelle_row)}) und 'Gesamtanzahl' "
            f"({len(anzahl_row)}) stimmt nicht ueberein - Datenfehler im Zoho-Export. "
            "Rechtsbuendig ausgerichtet (GESAMT bleibt korrekt), fehlende fuehrende "
            "Quellen-Eintraege haben anzahl=None."
        )
        diff = len(quelle_row) - len(anzahl_row)
        if diff > 0:
            anzahl_row = [None] * diff + anzahl_row
        else:
            quelle_row = [None] * (-diff) + quelle_row

    sources, gesamt = [], None
    for quelle, anzahl in zip(quelle_row, anzahl_row):
        quelle = quelle.strip() if quelle is not None else None
        if anzahl is None:
            n = None
        else:
            try:
                n = int(float(anzahl.strip()))
            except ValueError:
                n = None
        if quelle is not None and quelle.upper() == "GESAMT":
            gesamt = n
            continue
        sources.append({"quelle": quelle, "anzahl": n})
    return {"date": date, "sources": sources, "gesamt": gesamt, "warning": warning}


def _is_total_column(deal_name_val: str, produkt_val: str) -> bool:
    dn = (deal_name_val or "").strip().upper()
    pr = (produkt_val or "").strip().upper()
    return dn.startswith("GESAMT") or pr.startswith("ANZAHL")


def parse_abschluesse(text: str) -> list:
    """Parst die transponierte Abschluesse-*.csv: jede Zeile = ein Feld, jede
    Spalte ab 2 = ein Deal. Die letzte Spalte ist eine Summenspalte und wird
    verworfen. Rueckgabe: Liste von Rohe-Deal-Dicts
    (vorname, plz, produkt, betrag, datum, dealname)."""
    rows = _split_rows(text)
    field = {}
    for row in rows:
        cells = _split_cells(row)
        if not cells:
            continue
        field[cells[0].strip()] = cells[1:]

    vorname_col = field.get("Vorname", [])
    plz_col = field.get("PLZ", [])
    produkt_col = field.get("Produkt", [])
    betrag_col = field.get("Betrag", [])
    datum_col = field.get("Abschlussdatum", [])
    dealname_col = field.get("Deal-Name", [])

    n = max(len(vorname_col), len(dealname_col), len(produkt_col))
    deals = []
    for i in range(n):
        vorname = vorname_col[i].strip() if i < len(vorname_col) else ""
        plz = plz_col[i].strip() if i < len(plz_col) else ""
        produkt = produkt_col[i].strip() if i < len(produkt_col) else ""
        betrag = betrag_col[i].strip() if i < len(betrag_col) else ""
        datum = datum_col[i].strip() if i < len(datum_col) else ""
        dealname = dealname_col[i].strip() if i < len(dealname_col) else ""

        if not any([vorname, plz, produkt, betrag, datum, dealname]):
            continue  # leere Trailing-Spalte (Zoho haengt oft ein abschliessendes ";" an)
        if _is_total_column(dealname, produkt):
            continue  # Summen-/Total-Spalte am Ende, kein echter Einzel-Deal

        deals.append({
            "vorname": vorname or None,
            "plz": plz or None,
            "produkt": produkt or None,
            "betrag": betrag or None,
            "datum": datum or None,
            "dealname": dealname or produkt or None,
        })
    return deals


def abschluesse_to_processed_rows(deals: list) -> list:
    """Wandelt die rohen Abschluesse-Deals in dasselbe 'processed row'-Schema
    wie die Google-Sheet-Deals um (siehe lib/deal_processing.build_row),
    damit sie im Dashboard identisch verarbeitet werden (Region, Kategorie,
    Alterstendenz). Deals ohne verwertbares Datum/Betrag werden von
    build_row() selbst still uebersprungen (liefert dann None)."""
    out = []
    for d in deals:
        row = deal_processing.build_row(
            dealname=d.get("dealname"),
            betrag_raw=d.get("betrag"),
            plz_raw=d.get("plz"),
            vorname=d.get("vorname"),
            nachname=None,
            datum=d.get("datum"),
        )
        if row is not None:
            out.append(row)
    return out


# ---- Haupt-Einstiegspunkt ----

def fetch_latest_zoho_exports(folder_id: Optional[str] = None) -> dict:
    """Authentifiziert, listet den Drive-Ordner, waehlt pro Dateityp
    (top_tier / sm_leads / abschluesse) die zuletzt geaenderte Datei aus
    ('die neuesten 3 Dateien' - eine je Typ) und liefert die geparsten
    Inhalte zurueck. Wirft keine Exception nach aussen -> gibt bei Problemen
    ein Dict mit "error" zurueck, damit der Weekly-Job graceful skippen kann
    (gleiche Philosophie wie lib/config.py)."""
    if not config.get("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"):
        return {"error": "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON fehlt", "files_used": {}}
    try:
        token = _get_access_token()
        files = list_folder_files(folder_id, access_token=token)
        latest = pick_latest_per_type(files)

        result = {"error": None, "files_used": {}, "top_tier": None, "sm_leads": None, "abschluesse": []}
        for ftype, f in latest.items():
            result["files_used"][ftype] = {
                "name": f.get("name"), "modifiedTime": f.get("modifiedTime"), "id": f.get("id"),
            }
            text = download_file_text(f["id"], access_token=token)
            if ftype == "top_tier":
                result["top_tier"] = parse_pivot_counts(text)
            elif ftype == "sm_leads":
                result["sm_leads"] = parse_pivot_counts(text)
            elif ftype == "abschluesse":
                result["abschluesse"] = parse_abschluesse(text)
        return result
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        return {"error": f"HTTP {e.code}: {detail[:500]}", "files_used": {}}
    except Exception as e:
        return {"error": str(e), "files_used": {}}


if __name__ == "__main__":
    out = fetch_latest_zoho_exports()
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
