"""
HubSpot-Datenverarbeitung fuer das SPA-Deluxe Dashboard.

Zwei Betriebsarten:

1. Live (Produktion / GitHub Actions): `fetch_live_processed_rows(token)` zieht
   alle gewonnenen Deals direkt aus der HubSpot-API (kein manueller CSV-Export
   mehr noetig) und baut daraus die gleichen "processed rows" wie frueher aus
   den CSV-Exporten. Vorname/Nachname/PLZ kommen dabei vom mit dem Deal
   verknuepften Kontakt (Properties `firstname`/`lastname`/`zip`), da diese
   Felder NICHT am Deal selbst haengen.

2. Lokal/Debug: Wird die Datei direkt ausgefuehrt (`python3 lib/hubspot_processing.py`),
   liest sie wie frueher aus lokalen CSV-Exporten (siehe PATH/PATH7 unten) -
   praktisch zum Nachvollziehen/Testen der Kategorisierungs-Logik ohne
   API-Zugriff.

Property-Mapping (per HubSpot-API verifiziert, 2026-08-07):
  Deal:    dealname -> "Deal-Name", amount -> "Betrag", closedate -> "Abschlussdatum"
  Contact: firstname -> "Vorname", lastname -> "Nachname", zip -> "Postleitzahl"
  Won-Stages (isClosed=true, probability=1.0): "49352179" (Online) und
  "closedwon" (Ausstellung) in der "default" Sales-Pipeline.
"""
import csv, re, json, sys, time, urllib.request, urllib.error
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from name_ages import NAME_BIRTH_YEAR  # noqa: E402

PATH = '/Users/robertmedlin/Downloads/hubspot-custom-report-plz-name-summe-2026-08-06/hubspot-export-summary.csv'
PATH7 = '/Users/robertmedlin/Downloads/hubspot-custom-report-plz-name-summe-2026-08-07/hubspot-export-summary.csv'
CURRENT_YEAR = 2026

HUBSPOT_API = "https://api.hubapi.com"
WON_DEAL_STAGES = ["49352179", "closedwon"]  # default Sales-Pipeline, "gewonnen"

# ---------- Product categorization ----------
RULES = [
 ("Jacuzzi Swimspa", re.compile(r"power\s*pro|\bj[-\s]?1[69]\b", re.I)),
 ("Fisher Swimspa", re.compile(r"fisher|dual\s*zone|\b5[ds]\b", re.I)),
 ("Vortex Swimspa", re.compile(
     r"vortex|nitro|cobalt|cerium|neon|palladium|spectrum|"
     r"gemini|xenon|azure|mercury|titanium|\bikon\b|\beon\b|"
     r"aquagym|hydrozon|aquapace|aqualap|aqualounge|prestige",
     re.I)),
 ("Jacuzzi Whirlpool", re.compile(
     r"jacuzzi|onira|delfi|virtus|santorini|whirlwanne|"
     r"\bj[-\s]?\d{3}[a-z]?\b|\bj[-\s]?lxl\b|\blxl\b|\bunique\b", re.I)),
 ("Treesse Whirlpool", re.compile(
     r"treesse|\bheaven\b|\bshadow\b|aquarun|phantom|quarz|bioquant|"
     r"\bmuse\b|\bwave\b|\brest\b|\bfusion\b|maya|zen\s*active|soul\s*spa", re.I)),
 ("Villeroy & Boch Whirlpool", re.compile(r"villeroy|v\s*&\s*b|just\s*silence|\b[rax]\d[ldr]\b", re.I)),
 ("One Spa Whirlpool", re.compile(r"one\s*spa|city\s*spa|modena|milan", re.I)),
 ("Pacific Spa Whirlpool", re.compile(r"pacific|oceana", re.I)),
 ("Sauna", re.compile(r"sauna|suncube|auroom|thermalux", re.I)),
]

def categorize(name):
    for label, rx in RULES:
        if rx.search(name):
            return label
    return "Sonstiges / unbekannt"

TOP_CATEGORY_GROUP = {
 "Vortex Swimspa": "Swimspa", "Fisher Swimspa": "Swimspa", "Jacuzzi Swimspa": "Swimspa",
 "Jacuzzi Whirlpool": "Whirlpool", "Treesse Whirlpool": "Whirlpool",
 "Villeroy & Boch Whirlpool": "Whirlpool", "One Spa Whirlpool": "Whirlpool",
 "Pacific Spa Whirlpool": "Whirlpool", "Sauna": "Sauna", "Sonstiges / unbekannt": "Sonstiges",
}

# ---------- PLZ -> Region ----------
LEITZONE = {
 "0": "Sachsen / Suedthueringen (Dresden, Leipzig, Chemnitz)",
 "1": "Berlin / Brandenburg / Vorpommern",
 "2": "Hamburg / Schleswig-Holstein / Nord-Niedersachsen",
 "3": "Niedersachsen / Sachsen-Anhalt (Hannover, Magdeburg)",
 "4": "Nordrhein-Westfalen Nord (Ruhrgebiet, Muensterland)",
 "5": "Nordrhein-Westfalen Sued / Rheinland (Koeln, Bonn, Aachen)",
 "6": "Hessen / Rheinland-Pfalz Sued / Saarland",
 "7": "Baden-Wuerttemberg (Stuttgart, Nord/Ost)",
 "8": "Bayern Sued / Bodensee (Muenchen)",
 "9": "Bayern Nord/Mitte/Ost (Nuernberg)",
}
JUNK_PLZ = {"(kein wert)", "wird nachgereicht", "", "-", "n/a", "keine angabe"}

def normalize_plz(raw, dealname):
    raw = (raw or "").strip()
    low = raw.lower()
    if low in JUNK_PLZ or not raw:
        return None, "Unbekannt / kein Wert"
    m = re.search(r"\d{4,5}", raw)
    if not m:
        m2 = re.search(r"\b\d{5}\b", dealname)
        if m2:
            raw = m2.group(0)
        else:
            return None, "Unbekannt / Ausland (Text statt PLZ)"
    else:
        raw = m.group(0)
    if len(raw) == 5 and raw.isdigit():
        return raw, LEITZONE[raw[0]]
    if len(raw) == 4 and raw.isdigit():
        return raw, "Ausland (AT/CH/LU/BE, 4-stellige PLZ)"
    if len(raw) == 6 and raw.isdigit():
        raw5 = raw[:5]
        return raw5, LEITZONE[raw5[0]] + " (PLZ unsicher)"
    return None, "Unbekannt / Ausland (Text statt PLZ)"

# ---------- Name -> age band ----------
TITLE_STRIP = re.compile(r"^(herr|frau|dr\.?|familie|fam\.?|firma)\b\.?\s*", re.I)
UNUSABLE_VORNAME = {"(kein wert)", "herr", "frau", "familie", "fam", "fam.", "firma",
                     "dr", "dr.", "", "-", "n/a", "keine angabe", "unbekannt"}

def clean_first_token(vorname):
    v = (vorname or "").strip()
    if not v:
        return None
    tok = re.split(r"[\s]+", v)[0].strip(".,-").strip()
    return tok or None

def lookup_birth_year(tok):
    if not tok:
        return None
    by = NAME_BIRTH_YEAR.get(tok)
    if by is not None:
        return by
    for k, v in NAME_BIRTH_YEAR.items():
        if k.lower() == tok.lower():
            return v
    return None

def is_usable_vorname(vorname):
    v = (vorname or "").strip().lower()
    return v not in UNUSABLE_VORNAME and v != ""

COMPANY_HINTS = re.compile(
    r"gmbh|gbr\b|\bkg\b|\bag\b|\bug\b|e\.?k\.?\b|gartenbau|garten-\s*und|"
    r"landschaftsbau|gartendesign|pflasterunternehmen|bauunternehmen|"
    r"landschaftsarchitekt|greenkeeping|aquaristik|objekt\b", re.I)

def find_name_in_dealname(dealname):
    dn = (dealname or "").strip()
    if not dn or COMPANY_HINTS.search(dn):
        return None
    seg = re.split(r"[–\-|,]", dn, maxsplit=1)[0]
    seg = TITLE_STRIP.sub("", seg).strip()
    for raw_tok in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", seg):
        tok = raw_tok.strip(".,-")
        if len(tok) < 2:
            continue
        if tok.isupper():
            continue
        if lookup_birth_year(tok) is not None:
            return tok
    return None

def find_name_in_nachname_fullname(nachname):
    n = (nachname or "").strip()
    if not n or n.lower() in UNUSABLE_VORNAME:
        return None
    if " " not in n:
        return None
    tok = clean_first_token(n)
    if tok and lookup_birth_year(tok) is not None:
        return tok
    return None

def estimate_age_band(vorname, dealname=None, vorname_alt=None, nachname_alt=None):
    tok = clean_first_token(vorname) if is_usable_vorname(vorname) else None
    source = "vorname" if tok else None
    if tok is None and vorname_alt and is_usable_vorname(vorname_alt):
        cand = clean_first_token(vorname_alt)
        if cand and lookup_birth_year(cand) is not None:
            tok = cand
            source = "vorname_alt"
    if tok is None and dealname:
        cand = find_name_in_dealname(dealname)
        if cand:
            tok = cand
            source = "dealname"
    if tok is None and nachname_alt:
        cand = find_name_in_nachname_fullname(nachname_alt)
        if cand:
            tok = cand
            source = "nachname_fullname"
    by = lookup_birth_year(tok)
    if by is None:
        return None, None, None
    age = CURRENT_YEAR - by
    band_start = (age // 10) * 10
    band = f"{band_start}-{band_start+10}"
    return age, band, source

def _has_val(v):
    return bool(v) and v != "(Kein Wert)"

def build_row(dealname, betrag_raw, plz_raw, vorname, nachname, datum):
    """Baut aus den 6 HubSpot-Rohfeldern eine 'processed row' im Dashboard-Schema."""
    if not _has_val(datum):
        return None
    try:
        betrag = float(betrag_raw)
    except (ValueError, TypeError):
        return None

    year = datum[:4] if len(datum) >= 4 and datum[:4].isdigit() else None
    cat = categorize(dealname)
    group = TOP_CATEGORY_GROUP[cat]
    plz, region = normalize_plz(plz_raw, dealname)
    age, ageband, name_source = estimate_age_band(vorname, dealname)

    return {
        "deal": dealname, "betrag": betrag, "plz": plz, "region": region,
        "vorname": vorname, "nachname": nachname, "age": age, "ageband": ageband,
        "cat": cat, "group": group, "datum": datum, "year": year, "name_source": name_source,
    }

# =====================================================================
# Live-Pull ueber die HubSpot-API (Produktion)
# =====================================================================

def _api_request(token, path, method="GET", body=None, retries=3):
    url = f"{HUBSPOT_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
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
            raise RuntimeError(f"HubSpot API error {e.code} on {path}: {body_txt}") from e
        except urllib.error.URLError as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"HubSpot API request failed for {path}: {last_err}")


def fetch_won_deals(token):
    """Alle gewonnenen Deals (dealname, amount, closedate) via Search-API, paginiert."""
    deals = []
    after = None
    body_base = {
        "filterGroups": [{"filters": [
            {"propertyName": "dealstage", "operator": "IN", "values": WON_DEAL_STAGES},
        ]}],
        "properties": ["dealname", "amount", "closedate"],
        "limit": 100,
    }
    while True:
        body = dict(body_base)
        if after:
            body["after"] = after
        res = _api_request(token, "/crm/v3/objects/deals/search", method="POST", body=body)
        deals.extend(res.get("results", []))
        paging = res.get("paging") or {}
        after = (paging.get("next") or {}).get("after")
        if not after:
            break
    return deals


def fetch_deal_contact_ids(token, deal_ids):
    """Batch: deal_id -> erste zugeordnete contact_id (v4 Associations API)."""
    mapping = {}
    for i in range(0, len(deal_ids), 1000):
        chunk = deal_ids[i:i + 1000]
        body = {"inputs": [{"id": d} for d in chunk]}
        res = _api_request(token, "/crm/v4/associations/deals/contacts/batch/read",
                            method="POST", body=body)
        for r in res.get("results", []):
            deal_id = r.get("from", {}).get("id")
            tos = r.get("to") or []
            if deal_id and tos:
                mapping[deal_id] = str(tos[0].get("toObjectId"))
    return mapping


def fetch_contacts(token, contact_ids):
    """Batch: contact_id -> {firstname, lastname, zip} (v3 Batch Read API)."""
    props = {}
    uniq = list(dict.fromkeys(contact_ids))
    for i in range(0, len(uniq), 100):
        chunk = uniq[i:i + 100]
        body = {"properties": ["firstname", "lastname", "zip"],
                 "inputs": [{"id": c} for c in chunk]}
        res = _api_request(token, "/crm/v3/objects/contacts/batch/read",
                            method="POST", body=body)
        for r in res.get("results", []):
            props[r["id"]] = r.get("properties", {})
    return props


def fetch_live_processed_rows(token):
    """Zieht alle gewonnenen Deals + verknuepfte Kontakte live aus HubSpot und
    baut daraus die 'processed rows' im gleichen Schema wie der alte CSV-Import."""
    deals = fetch_won_deals(token)
    deal_ids = [d["id"] for d in deals]
    deal_to_contact = fetch_deal_contact_ids(token, deal_ids)
    contact_ids = list(deal_to_contact.values())
    contacts = fetch_contacts(token, contact_ids)

    rows_out = []
    for d in deals:
        p = d.get("properties", {})
        dealname = (p.get("dealname") or "").strip()
        betrag_raw = p.get("amount")
        datum = (p.get("closedate") or "")[:10]  # ISO date, Zeit abschneiden

        contact_id = deal_to_contact.get(d["id"])
        cprops = contacts.get(contact_id, {}) if contact_id else {}
        vorname = (cprops.get("firstname") or "").strip()
        nachname = (cprops.get("lastname") or "").strip()
        plz_raw = (cprops.get("zip") or "").strip()

        row = build_row(dealname, betrag_raw, plz_raw, vorname, nachname, datum)
        if row:
            rows_out.append(row)
    return rows_out


# =====================================================================
# Lokaler CSV-Debug-Modus (nur bei direktem Skriptaufruf, kein API-Token noetig)
# =====================================================================

def key7(row):
    return (row["Deal-Name"].strip(), row["Betrag"].strip(), (row.get("Postleitzahl") or "").strip())


def _run_csv_debug():
    idx7 = defaultdict(list)
    with open(PATH7, encoding="utf-8-sig") as f7:
        for row in csv.DictReader(f7):
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            idx7[key7(row)].append(row)

    ambiguous7 = 0
    lookup7 = {}
    for k, cands in idx7.items():
        if len(cands) == 1:
            lookup7[k] = cands[0]
        else:
            ambiguous7 += 1
    print(f"2026-08-07 export: {len(idx7)} unique (deal,betrag,plz) keys, {ambiguous7} ambiguous (skipped for safety)")

    rows_out = []
    name_source_count = Counter()

    with open(PATH, encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            dealname = row["Deal-Name"]
            plz_raw = row["Postleitzahl"]
            vorname = row["Vorname"]
            nachname = row.get("Nachname", "")
            datum = row.get("Abschlussdatum – monatlich", "")
            row7 = lookup7.get((dealname.strip(), row["Betrag"].strip(), (plz_raw or "").strip()))
            vorname7 = row7.get("Vorname") if row7 else None
            nachname7 = row7.get("Nachname") if row7 else None

            if not _has_val(datum):
                continue
            try:
                betrag = float(row["Betrag"])
            except (ValueError, TypeError):
                continue

            year = datum[:4] if len(datum) >= 4 and datum[:4].isdigit() else None
            cat = categorize(dealname)
            group = TOP_CATEGORY_GROUP[cat]
            plz, region = normalize_plz(plz_raw, dealname)
            age, ageband, name_source = estimate_age_band(vorname, dealname, vorname7, nachname7)
            if name_source:
                name_source_count[name_source] += 1

            rows_out.append({
                "deal": dealname, "betrag": betrag, "plz": plz, "region": region,
                "vorname": vorname, "nachname": nachname, "age": age, "ageband": ageband,
                "cat": cat, "group": group, "datum": datum, "year": year, "name_source": name_source,
            })

    print("Total rows:", len(rows_out))
    print("Total Umsatz:", sum(x["betrag"] for x in rows_out))
    print("Rows with age estimate:", sum(1 for x in rows_out if x["ageband"]))
    print("Rows with region:", sum(1 for x in rows_out if x["region"] and "Unbekannt" not in x["region"]))
    print("Name-Quelle fuer Altersschaetzung:", dict(name_source_count))

    unresolved = [x for x in rows_out if x["ageband"] is None]
    print("Weiterhin unbekanntes Alter:", len(unresolved), "Umsatz:", sum(x["betrag"] for x in unresolved))

    catcount = Counter(x["cat"] for x in rows_out)
    catrev = defaultdict(float)
    for x in rows_out:
        catrev[x["cat"]] += x["betrag"]
    print("\n--- Kategorien (Anzahl / Umsatz) ---")
    for k, v in sorted(catcount.items(), key=lambda kv: -catrev[kv[0]]):
        print(f"{k:30s} n={v:5d}  umsatz={catrev[k]:,.0f}")

    json.dump(rows_out, open("/tmp/processed_rows.json", "w"), ensure_ascii=False)
    print("\nsaved /tmp/processed_rows.json")


if __name__ == "__main__":
    _run_csv_debug()
