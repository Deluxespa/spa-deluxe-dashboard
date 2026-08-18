"""
CRM-unabhängige Deal-Verarbeitung fuer das SPA-Deluxe Dashboard.

Diese Logik (Produktkategorisierung, PLZ->Region, Namens-/Altersschaetzung,
"processed row"-Schema) ist komplett unabhaengig davon, aus welchem CRM die
Rohdaten (Deal-Name, Betrag, PLZ, Vorname, Nachname, Abschlussdatum) kommen.
Frueher kam das aus HubSpot (siehe Git-Historie / lib/hubspot_processing.py),
seit 2026-08 kommt es aus Zoho CRM ueber ein Google Sheet (siehe
lib/gsheet_processing.py).

`build_row(...)` ist die zentrale Funktion, die jeder CRM-spezifische Fetcher
(z.B. `lib/gsheet_processing.fetch_live_processed_rows`) am Ende aufruft, um
aus den 6 Rohfeldern eine "processed row" im Dashboard-Schema zu bauen.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from name_ages import NAME_BIRTH_YEAR  # noqa: E402

CURRENT_YEAR = 2026

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
    """Baut aus den 6 CRM-Rohfeldern (Deal-Name, Betrag, PLZ, Vorname, Nachname,
    Abschlussdatum) eine 'processed row' im Dashboard-Schema. CRM-unabhaengig -
    egal ob die Rohwerte aus Zoho, HubSpot oder einem CSV-Export kommen."""
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
