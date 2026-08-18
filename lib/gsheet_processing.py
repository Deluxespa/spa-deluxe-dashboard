"""
Google-Sheets-Datenverarbeitung fuer das SPA-Deluxe Dashboard.

Ersetzt seit 2026-08 die direkte Zoho-CRM-API-Anbindung (siehe Git-Historie).
Zoho liefert die gewonnenen Deals nicht mehr per API-Direktanbindung, sondern
schreibt sie ueber eine Zoho-Automatisierung
(native "Export to Google Sheets"-Extension, oder Zapier/Make) in ein Google
Sheet. Dieses Modul liest das Sheet nur noch READ-ONLY aus und baut daraus
dieselben "processed rows" wie zuvor (siehe lib/deal_processing.build_row).

Vorteil ggue. dem direkten API-Weg: kein OAuth2-Refresh-Token-Handling fuer
Zoho noetig, die Rohdaten sind fuer Menschen im Sheet sichtbar/pruefbar, und
die Spaltennamen legst du selbst fest statt Zoho-interne Feld-API-Namen
erraten zu muessen.

Benoetigte Secrets (siehe .env.example / lib/config.py SECRET_GROUPS):
  GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON  - kompletter Inhalt der Service-Account-
                                         JSON-Key-Datei (Google Cloud Console
                                         -> IAM & Admin -> Dienstkonten -> Key
                                         erstellen), als EINE Zeile/String.
  GOOGLE_SHEETS_SPREADSHEET_ID        - ID aus der Sheet-URL:
                                         https://docs.google.com/spreadsheets/d/<DIESE_ID>/edit
Optional:
  GOOGLE_SHEETS_RANGE   (Default: "Deals!A:Z")
  WON_DEAL_STAGES        (Default: "Closed Won" - Komma-separierte Liste,
                          nur relevant falls eine "Stage"-Spalte im Sheet
                          existiert; fehlt die Spalte, wird angenommen, dass
                          im Sheet ohnehin nur bereits gewonnene Deals stehen)

WICHTIG - erwartete Spaltenkoepfe (Reihenfolge egal, Gross/Kleinschreibung
egal, in der ERSTEN Zeile des Tabs):
  Deal Name | Amount | Closing Date | Stage | First Name | Last Name | Mailing Zip
Deutsche Alternativen werden ebenfalls erkannt (Titel/Betrag/Datum/Status/
Vorname/Nachname/PLZ/Postleitzahl), siehe _HEADER_ALIASES unten. Nur
"Deal Name", "Amount" und "Closing Date" sind Pflichtspalten.

Freigabe nicht vergessen: Das Sheet muss fuer die Service-Account-E-Mail-
Adresse (steht im JSON-Key als "client_email") mindestens als "Betrachter"
freigegeben werden - sonst schlaegt der Read mit HTTP 403 fehl.
"""
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from deal_processing import build_row  # noqa: E402

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"
DEFAULT_RANGE = "Deals!A:Z"
GOOGLE_SHEETS_EPOCH = date(1899, 12, 30)  # Serial-Date-Basis von Google Sheets

_default_won_stages = "Closed Won"
WON_DEAL_STAGES = [
    s.strip().lower()
    for s in config.get("WON_DEAL_STAGES", _default_won_stages).split(",")
    if s.strip()
]

# logischer Spaltenname -> erkannte Ueberschriften-Varianten (normalisiert: lower + strip)
_HEADER_ALIASES = {
    "dealname": {"deal name", "dealname", "deal", "titel", "title"},
    "amount": {"amount", "betrag"},
    "closing_date": {"closing date", "closedate", "close date", "datum"},
    "stage": {"stage", "phase", "status"},
    "first_name": {"first name", "firstname", "vorname"},
    "last_name": {"last name", "lastname", "nachname"},
    "zip": {"mailing zip", "zip code", "zip", "plz", "postleitzahl"},
}
_REQUIRED_COLUMNS = ("dealname", "amount", "closing_date")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _load_service_account() -> dict:
    raw = config.require("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON ist kein gueltiges JSON. Bitte den "
            "kompletten Inhalt der von Google heruntergeladenen Service-Account-"
            "Key-Datei (als eine Zeile) als Wert setzen."
        ) from e


def _get_access_token() -> str:
    """Baut einen selbst-signierten JWT (Service-Account 'two-legged OAuth')
    und tauscht ihn gegen einen kurzlebigen Access-Token. Kein Refresh-Token
    noetig - der private Key im JSON-Key IST das Langzeit-Credential."""
    sa = _load_service_account()
    token_uri = sa.get("token_uri", TOKEN_URI_DEFAULT)
    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "scope": SHEETS_SCOPE,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    header = {"alg": "RS256", "typ": "JWT"}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    key = RSA.import_key(sa["private_key"])
    signature = pkcs1_15.new(key).sign(SHA256.new(signing_input.encode()))
    assertion = f"{signing_input}.{_b64url(signature)}"

    body = (
        "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer"
        f"&assertion={assertion}"
    ).encode()
    req = urllib.request.Request(token_uri, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Google Service-Account Token-Request fehlgeschlagen ({e.code}): "
            f"{e.read().decode(errors='replace')}"
        ) from e
    token = data.get("access_token")
    if not token:
        raise RuntimeError(
            f"Google Service-Account Token-Request: keine access_token im Response: {data}"
        )
    return token


def fetch_sheet_values(access_token: str) -> list:
    """Holt alle Zeilen (inkl. Header) aus dem konfigurierten Sheet/Range,
    als UNFORMATTED_VALUE (rohe Zahlen statt formatierter Strings, damit
    Betraege direkt als float nutzbar sind)."""
    spreadsheet_id = config.require("GOOGLE_SHEETS_SPREADSHEET_ID")
    rng = config.get("GOOGLE_SHEETS_RANGE", DEFAULT_RANGE)
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/"
        f"{urllib.parse.quote(rng, safe='')}"
        f"?majorDimension=ROWS&valueRenderOption=UNFORMATTED_VALUE"
    )
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Google Sheets Read fehlgeschlagen ({e.code}): "
            f"{e.read().decode(errors='replace')} - Ist das Sheet fuer die "
            f"Service-Account-E-Mail (client_email im JSON-Key) freigegeben?"
        ) from e
    return data.get("values") or []


def _build_header_map(header_row: list) -> dict:
    """Ordnet jeder erkannten logischen Spalte (dealname/amount/...) den
    Spaltenindex zu, anhand der Ueberschriften-Zeile."""
    normalized = [str(h).strip().lower() for h in header_row]
    col_map = {}
    for logical, aliases in _HEADER_ALIASES.items():
        for idx, h in enumerate(normalized):
            if h in aliases:
                col_map[logical] = idx
                break
    fehlend = [k for k in _REQUIRED_COLUMNS if k not in col_map]
    if fehlend:
        raise RuntimeError(
            f"Google Sheet: Pflichtspalten nicht gefunden: {fehlend}. Gefundene "
            f"Ueberschriften: {header_row!r}. Siehe Modul-Docstring von "
            f"lib/gsheet_processing.py fuer die erwarteten Spaltennamen."
        )
    return col_map


def _cell(row: list, idx):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _cell_str(row: list, idx) -> str:
    val = _cell(row, idx)
    return "" if val is None else str(val).strip()


def _parse_amount(row: list, idx) -> str:
    """UNFORMATTED_VALUE liefert Zahlen normalerweise schon als float/int.
    Fallback fuer den Fall, dass die Spalte trotzdem als Text vorliegt
    (z.B. '3.499,00' im deutschen Format oder '3499')."""
    val = _cell(row, idx)
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val or "").strip()
    if not s:
        return ""
    try:
        float(s)
        return s
    except ValueError:
        pass
    # Deutsches Format: Tausenderpunkt raus, Komma -> Punkt
    return _normalize_amount_text(s)


def _normalize_amount_text(s: str) -> str:
    s = re.sub(r"[^\d,.\-]", "", s)  # Waehrungssymbole/Leerzeichen weg
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return s


def _parse_closing_date(row: list, idx) -> str:
    """Gibt ein ISO-Datum 'YYYY-MM-DD' zurueck. UNFORMATTED_VALUE liefert
    Datumszellen als Serial-Number (Tage seit 1899-12-30) - die wandeln wir
    hier um. Liegt stattdessen schon ein String vor (z.B. weil die Spalte als
    Text formatiert ist), werden gaengige Formate versucht."""
    val = _cell(row, idx)
    if isinstance(val, (int, float)):
        try:
            return (GOOGLE_SHEETS_EPOCH + timedelta(days=val)).isoformat()
        except OverflowError:
            return ""
    s = str(val or "").strip()
    if not s:
        return ""
    if len(s) >= 10 and s[:4].isdigit() and s[4] in "-/":
        return s[:10].replace("/", "-")
    for fmt in ("%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s  # unbekanntes Format - build_row() ignoriert das Jahr dann einfach


def fetch_live_processed_rows() -> list:
    """Liest das Google Sheet und baut daraus die 'processed rows' im
    gleichen Schema wie zuvor bei der direkten Zoho-API/HubSpot (siehe
    lib/deal_processing.build_row)."""
    access_token = _get_access_token()
    values = fetch_sheet_values(access_token)
    if not values:
        return []

    header_row, *data_rows = values
    col_map = _build_header_map(header_row)
    has_stage_col = "stage" in col_map

    rows_out = []
    for row in data_rows:
        if not any(c not in (None, "") for c in row):
            continue  # leere Zeile ueberspringen

        if has_stage_col:
            stage_val = _cell_str(row, col_map["stage"]).lower()
            if stage_val not in WON_DEAL_STAGES:
                continue

        dealname = _cell_str(row, col_map.get("dealname"))
        betrag_raw = _parse_amount(row, col_map.get("amount"))
        datum = _parse_closing_date(row, col_map.get("closing_date"))
        vorname = _cell_str(row, col_map.get("first_name"))
        nachname = _cell_str(row, col_map.get("last_name"))
        plz_raw = _cell_str(row, col_map.get("zip"))

        built = build_row(dealname, betrag_raw, plz_raw, vorname, nachname, datum)
        if built:
            rows_out.append(built)
    return rows_out


if __name__ == "__main__":
    # Lokaler Testlauf: python3 lib/gsheet_processing.py
    # (braucht gesetzte GOOGLE_SHEETS_* Secrets in .env)
    out = fetch_live_processed_rows()
    print(f"{len(out)} gewonnene Deals aus Google Sheet gezogen.")
    print(json.dumps(out[:3], ensure_ascii=False, indent=2))
