"""
Zoho-CRM-Datenverarbeitung fuer das SPA-Deluxe Dashboard.

Ersetzt seit 2026-08 die fruehere HubSpot-Anbindung (siehe Git-Historie /
lib/hubspot_processing.py) - HubSpot wird nicht mehr genutzt, alle Leads/
Deals kommen jetzt aus Zoho CRM.

Funktionsweise: `fetch_live_processed_rows()` holt sich per OAuth2
(Refresh-Token-Flow, "Self Client") einen Access-Token und zieht dann ueber
Zoho's COQL-API (SELECT ... FROM Deals WHERE Stage = ...) alle gewonnenen
Deals INKLUSIVE der verknuepften Kontaktdaten (Vorname/Nachname/PLZ) in
EINER Abfrage - anders als bei HubSpot ist dafuer kein separater
Assoziations-Call noetig, weil Zoho verknuepfte Modul-Felder per
Punkt-Notation (`Contact_Name.First_Name` etc.) direkt in der COQL-Query
erlaubt.

Benoetigte Secrets (siehe .env.example / lib/config.py SECRET_GROUPS):
  ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN
Optional (Default = EU-Rechenzentrum, da SPA Deluxe in Deutschland sitzt):
  ZOHO_ACCOUNTS_URL   (Default: https://accounts.zoho.eu)
  ZOHO_API_DOMAIN     (Default: https://www.zohoapis.eu)
  ZOHO_WON_STAGES     (Default: "Closed Won" - Komma-separierte Liste, falls
                        im Zoho-Account mehrere "gewonnen"-Stages existieren,
                        z.B. "Closed Won,Closed Won With Down Payment")

WICHTIG: Die exakten API-Namen der Felder unten (Deal_Name, Amount,
Closing_Date, Stage, Contact_Name, First_Name, Last_Name, Mailing_Zip) sind
die Zoho-CRM-Standardfelder ("out of the box"). Falls im echten Zoho-Account
andere/benutzerdefinierte Feld-API-Namen verwendet werden (z.B. eine eigene
"PLZ"-Feld statt Mailing_Zip), einfach die Konstanten FIELD_* unten anpassen -
der Rest (Kategorisierung, Region, Altersschaetzung) bleibt unveraendert,
siehe lib/deal_processing.py.
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from deal_processing import build_row  # noqa: E402

ZOHO_ACCOUNTS_URL = config.get("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.eu").rstrip("/")
ZOHO_API_DOMAIN = config.get("ZOHO_API_DOMAIN", "https://www.zohoapis.eu").rstrip("/")

_default_won_stages = "Closed Won"
WON_DEAL_STAGES = [
    s.strip() for s in config.get("ZOHO_WON_STAGES", _default_won_stages).split(",") if s.strip()
]

# ---- Zoho CRM Standard-Feld-API-Namen (bei Bedarf anpassen) ----
FIELD_DEAL_NAME = "Deal_Name"
FIELD_AMOUNT = "Amount"
FIELD_CLOSING_DATE = "Closing_Date"
FIELD_STAGE = "Stage"
FIELD_CONTACT_FIRST_NAME = "Contact_Name.First_Name"
FIELD_CONTACT_LAST_NAME = "Contact_Name.Last_Name"
FIELD_CONTACT_ZIP = "Contact_Name.Mailing_Zip"

COQL_PAGE_SIZE = 200  # Zoho COQL Maximum pro Request


def _get_access_token() -> str:
    """Tauscht den (langlebigen) Refresh-Token gegen einen kurzlebigen
    Access-Token. Wird bei jedem Lauf einmal frisch geholt (kein Caching
    noetig, der Job laeuft nur 1x/Woche)."""
    client_id = config.require("ZOHO_CLIENT_ID")
    client_secret = config.require("ZOHO_CLIENT_SECRET")
    refresh_token = config.require("ZOHO_REFRESH_TOKEN")

    url = f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token"
    body = (
        f"refresh_token={refresh_token}"
        f"&client_id={client_id}"
        f"&client_secret={client_secret}"
        f"&grant_type=refresh_token"
    ).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Zoho OAuth Token-Refresh fehlgeschlagen ({e.code}): "
            f"{e.read().decode(errors='replace')}"
        ) from e
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Zoho OAuth Token-Refresh: keine access_token im Response: {data}")
    return token


def _coql_request(access_token: str, query: str, retries: int = 3) -> dict:
    url = f"{ZOHO_API_DOMAIN}/crm/v6/coql"
    body = json.dumps({"select_query": query}).encode()
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_txt = e.read().decode(errors="replace")
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"Zoho COQL-Request fehlgeschlagen ({e.code}): {body_txt}") from e
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"Zoho COQL-Request fehlgeschlagen: {last_err}")


def fetch_won_deals(access_token: str) -> list:
    """Alle gewonnenen Deals INKLUSIVE der verknuepften Kontaktdaten
    (Vorname/Nachname/PLZ), paginiert ueber COQL (max 200 Zeilen/Request)."""
    stage_list = ", ".join(f"'{s}'" for s in WON_DEAL_STAGES)
    fields = ", ".join([
        FIELD_DEAL_NAME, FIELD_AMOUNT, FIELD_CLOSING_DATE,
        FIELD_CONTACT_FIRST_NAME, FIELD_CONTACT_LAST_NAME, FIELD_CONTACT_ZIP,
    ])
    rows = []
    offset = 0
    while True:
        query = (
            f"SELECT {fields} FROM Deals "
            f"WHERE {FIELD_STAGE} in ({stage_list}) "
            f"LIMIT {offset}, {COQL_PAGE_SIZE}"
        )
        res = _coql_request(access_token, query)
        chunk = res.get("data") or []
        rows.extend(chunk)
        if not res.get("info", {}).get("more_records"):
            break
        offset += COQL_PAGE_SIZE
    return rows


def _dig(d: dict, dotted_key: str):
    """COQL gibt verknuepfte Felder ('Contact_Name.First_Name') als
    verschachteltes Dict zurueck: {"Contact_Name": {"First_Name": "..."}}."""
    cur = d
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def fetch_live_processed_rows() -> list:
    """Zieht alle gewonnenen Deals + verknuepfte Kontakte live aus Zoho CRM
    und baut daraus die 'processed rows' im gleichen Schema wie zuvor bei
    HubSpot (siehe lib/deal_processing.build_row)."""
    access_token = _get_access_token()
    deals = fetch_won_deals(access_token)

    rows_out = []
    for d in deals:
        dealname = (d.get(FIELD_DEAL_NAME) or "").strip()
        betrag_raw = d.get(FIELD_AMOUNT)
        datum_raw = d.get(FIELD_CLOSING_DATE) or ""
        datum = datum_raw[:10]  # ISO-Datum, Zeit abschneiden

        vorname = (_dig(d, FIELD_CONTACT_FIRST_NAME) or "").strip()
        nachname = (_dig(d, FIELD_CONTACT_LAST_NAME) or "").strip()
        plz_raw = str(_dig(d, FIELD_CONTACT_ZIP) or "").strip()

        row = build_row(dealname, betrag_raw, plz_raw, vorname, nachname, datum)
        if row:
            rows_out.append(row)
    return rows_out


if __name__ == "__main__":
    # Lokaler Testlauf: python3 lib/zoho_processing.py
    # (braucht gesetzte ZOHO_* Secrets in .env)
    out = fetch_live_processed_rows()
    print(f"{len(out)} gewonnene Deals aus Zoho gezogen.")
    print(json.dumps(out[:3], ensure_ascii=False, indent=2))
