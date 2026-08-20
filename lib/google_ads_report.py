"""
Google-Ads-Anbindung ueber ein manuell gepflegtes Google Sheet (kein Ads-API-
Zugang noetig). Der Nutzer laedt/aktualisiert woechentlich (typischerweise
montags) das Sheet "Google Ads Wochenbericht" im selben Google-Drive-Ordner
wie die Zoho-CRM-Exporte ("Zoho CRM Exporte", siehe lib/zoho_drive_import.py).

Das Sheet enthaelt zwei relevante Tabellenblaetter:

  - "Ausgaben"   -> einfache Kennzahlen-Liste (Stand-Datum, Ausgaben aktueller
                    Monat, Ausgaben aktuelles Jahr YTD, Konto). Das ist die
                    Quelle fuer die Hero-Karte (Ads-Spend/MER).
  - "Kampagnen"   -> eine Zeile pro Google-Ads-Kampagne mit Spend, Conversions,
                    Inbound Calls, Usermaven-Zahlen, Deal gewonnen, Lead: Zoho
                    und Conversion-Wert. Letzte Zeile ("GESAMT") ist eine
                    Summenzeile und wird beim Parsen als eigenes "total"-Feld
                    ausgewiesen (nicht Teil der campaigns-Liste).

WICHTIG: Wir lesen ueber die Sheets-API mit valueRenderOption=UNFORMATTED_VALUE,
d.h. echte Zahlen (floats) direkt aus den Zellen - nicht ueber einen CSV-/Text-
Export, da bei Letzterem das deutsche Dezimalkomma mit dem CSV-Trennzeichen
kollidiert und Werte falsch aufgespalten wuerden (gleiche Problemklasse wie bei
den Zoho-Exporten, siehe lib/zoho_drive_import.py).

Dieses Modul ist bewusst unabhaengig von lib/gsheet_processing.py und
lib/zoho_drive_import.py gehalten (eigene, minimale JWT-Auth gegen dieselbe
Google-Service-Account-Identitaet), verwendet aber das identische Auth-Muster
(zwei-legged OAuth2 per selbst-signiertem JWT, kein Refresh-Token noetig).
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

from lib import config

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"
GOOGLE_SHEETS_EPOCH = date(1899, 12, 30)  # Serial-Date-Basis von Google Sheets

# Spreadsheet "Google Ads Wochenbericht" im Ordner "Zoho CRM Exporte" (per ENV
# ueberschreibbar, falls das Sheet mal an einem anderen Ort landet/neu angelegt wird).
GOOGLE_ADS_REPORT_SHEET_ID_DEFAULT = "1eZG60hYhcixQPbCM7hMFuKD213YmItkk8Jg25tb_ZpA"

AUSGABEN_RANGE_DEFAULT = "Ausgaben!A:B"
KAMPAGNEN_RANGE_DEFAULT = "Kampagnen!A:I"

_CAMPAIGN_FIELDS = [
    "name",
    "spend_eur",
    "conversions_all",
    "inbound_call",
    "usermaven_all",
    "usermaven_top_tier",
    "deal_won",
    "lead_zoho",
    "conv_value_eur",
]


def _sheet_id() -> str:
    return config.get("GOOGLE_ADS_REPORT_SHEET_ID", GOOGLE_ADS_REPORT_SHEET_ID_DEFAULT)


def _load_service_account() -> dict:
    raw = config.require("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON")
    return json.loads(raw)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _get_access_token() -> str:
    from Crypto.Hash import SHA256
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15

    sa = _load_service_account()
    token_uri = sa.get("token_uri") or TOKEN_URI_DEFAULT
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": SHEETS_SCOPE,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    key = RSA.import_key(sa["private_key"])
    signature = pkcs1_15.new(key).sign(SHA256.new(signing_input.encode("ascii")))
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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Google-OAuth (Sheets, Ads-Report): Token-Request fehlgeschlagen "
            f"({e.code}): {e.read().decode(errors='replace')}"
        ) from e
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Google-OAuth (Sheets, Ads-Report): kein access_token in Antwort: {data}")
    return token


def fetch_values(rng: str, access_token: str, spreadsheet_id: str = None) -> list:
    """Holt alle Zeilen (inkl. Header) aus dem angegebenen Tabellenblatt/Range
    des Google-Ads-Wochenbericht-Sheets, als UNFORMATTED_VALUE (rohe Zahlen)."""
    spreadsheet_id = spreadsheet_id or _sheet_id()
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
            f"Google Ads Wochenbericht - Sheet-Read fehlgeschlagen ({e.code}, Range={rng}): "
            f"{e.read().decode(errors='replace')} - ist das Sheet fuer die "
            f"Service-Account-E-Mail (client_email im JSON-Key) freigegeben?"
        ) from e
    return data.get("values") or []


def _num(v) -> float:
    """UNFORMATTED_VALUE liefert Zahlen bereits als int/float. Leere Zellen
    oder gelegentliche Text-Reste werden defensiv zu 0.0."""
    if isinstance(v, (int, float)):
        return float(v)
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return 0.0


def parse_ausgaben(rows: list) -> dict:
    """Parst das "Ausgaben"-Tabellenblatt (einfache Key/Value-Liste, keine
    Kopfzeile): Stand, Ausgaben aktueller Monat, Ausgaben aktuelles Jahr YTD, Konto."""
    out = {"stand": None, "spend_current_month_eur": None, "spend_ytd_eur": None, "account": None}
    for row in rows:
        if len(row) < 2:
            continue
        label = str(row[0]).strip().lower()
        value = row[1]
        if label.startswith("stand"):
            if isinstance(value, (int, float)):
                out["stand"] = (GOOGLE_SHEETS_EPOCH + timedelta(days=value)).isoformat()
            else:
                out["stand"] = str(value)
        elif "aktueller monat" in label:
            out["spend_current_month_eur"] = round(_num(value), 2)
        elif "ytd" in label or "aktuelles jahr" in label:
            out["spend_ytd_eur"] = round(_num(value), 2)
        elif label.startswith("konto"):
            out["account"] = str(value)
    return out


def parse_kampagnen(rows: list) -> dict:
    """Parst das "Kampagnen"-Tabellenblatt: Kopfzeile + eine Zeile pro Kampagne,
    letzte Zeile "GESAMT" ist eine Summenzeile -> eigenes total-Feld."""
    if not rows:
        return {"campaigns": [], "total": None}
    campaigns = []
    total = None
    for row in rows[1:]:
        if not row or not str(row[0]).strip():
            continue
        name = str(row[0]).strip()
        vals = [_num(row[i]) if i < len(row) else 0.0 for i in range(1, len(_CAMPAIGN_FIELDS))]
        record = dict(zip(_CAMPAIGN_FIELDS[1:], vals))
        record["name"] = name
        if name.strip().upper() == "GESAMT":
            total = record
        else:
            campaigns.append(record)
    campaigns.sort(key=lambda c: c.get("spend_eur", 0.0), reverse=True)
    return {"campaigns": campaigns, "total": total}


def fetch_google_ads_report() -> dict:
    """Holt Ausgaben + Kampagnen-Uebersicht aus dem Google-Ads-Wochenbericht-Sheet.
    Gibt bei jedem Fehler (Secrets fehlen, Sheet nicht freigegeben, Netzwerk,
    Tabellenblatt fehlt) ein Dict mit "error" zurueck statt zu crashen - der
    Rest der Pipeline soll auch ohne diese Quelle weiterlaufen (siehe Prinzip
    in lib/zoho_drive_import.py)."""
    try:
        token = _get_access_token()
        ausgaben_rows = fetch_values(AUSGABEN_RANGE_DEFAULT, token)
        kampagnen_rows = fetch_values(KAMPAGNEN_RANGE_DEFAULT, token)
        ausgaben = parse_ausgaben(ausgaben_rows)
        kampagnen = parse_kampagnen(kampagnen_rows)
        return {
            **ausgaben,
            "campaigns": kampagnen["campaigns"],
            "campaigns_total": kampagnen["total"],
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    print(json.dumps(fetch_google_ads_report(), indent=2, ensure_ascii=False)[:3000])
