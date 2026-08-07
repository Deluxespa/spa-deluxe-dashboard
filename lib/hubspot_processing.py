import csv, re, json, sys
sys.path.insert(0,'/tmp')
from name_ages import NAME_BIRTH_YEAR
from collections import Counter, defaultdict

PATH='/Users/robertmedlin/Downloads/hubspot-custom-report-plz-name-summe-2026-08-06/hubspot-export-summary.csv'
PATH7='/Users/robertmedlin/Downloads/hubspot-custom-report-plz-name-summe-2026-08-07/hubspot-export-summary.csv'
CURRENT_YEAR=2026

# ---------- Product categorization ----------
RULES=[
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
 "Vortex Swimspa":"Swimspa", "Fisher Swimspa":"Swimspa", "Jacuzzi Swimspa":"Swimspa",
 "Jacuzzi Whirlpool":"Whirlpool", "Treesse Whirlpool":"Whirlpool",
 "Villeroy & Boch Whirlpool":"Whirlpool", "One Spa Whirlpool":"Whirlpool",
 "Pacific Spa Whirlpool":"Whirlpool", "Sauna":"Sauna", "Sonstiges / unbekannt":"Sonstiges",
}

# ---------- PLZ -> Region ----------
LEITZONE = {
 "0":"Sachsen / Südthüringen (Dresden, Leipzig, Chemnitz)",
 "1":"Berlin / Brandenburg / Vorpommern",
 "2":"Hamburg / Schleswig-Holstein / Nord-Niedersachsen",
 "3":"Niedersachsen / Sachsen-Anhalt (Hannover, Magdeburg)",
 "4":"Nordrhein-Westfalen Nord (Ruhrgebiet, Münsterland)",
 "5":"Nordrhein-Westfalen Süd / Rheinland (Köln, Bonn, Aachen)",
 "6":"Hessen / Rheinland-Pfalz Süd / Saarland",
 "7":"Baden-Württemberg (Stuttgart, Nord/Ost)",
 "8":"Bayern Süd / Bodensee (München)",
 "9":"Bayern Nord/Mitte/Ost (Nürnberg)",
}
JUNK_PLZ = {"(kein wert)","wird nachgereicht","","-","n/a","keine angabe"}
def normalize_plz(raw, dealname):
    raw=(raw or "").strip()
    low=raw.lower()
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
UNUSABLE_VORNAME = {"(kein wert)","herr","frau","familie","fam","fam.","firma",
                     "dr","dr.","","-","n/a","keine angabe","unbekannt"}

def clean_first_token(vorname):
    v=(vorname or "").strip()
    if not v: return None
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

# NEW: sometimes the HubSpot export has an unusable/empty "Vorname" but the
# full "Vorname Nachname" string got stuffed into the "Nachname" column
# instead (confirmed by cross-checking the 2026-08-07 export, e.g.
# Vorname="(Kein Wert)", Nachname="Alexander Reuter"). If so, the first
# token of that string is a usable first name.
def find_name_in_nachname_fullname(nachname):
    n = (nachname or "").strip()
    if not n or n.lower() in UNUSABLE_VORNAME:
        return None
    if " " not in n:
        return None  # a lone surname carries no first-name info
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
            source = "vorname_2026-08-07"
    if tok is None and dealname:
        cand = find_name_in_dealname(dealname)
        if cand:
            tok = cand
            source = "dealname"
    if tok is None and nachname_alt:
        cand = find_name_in_nachname_fullname(nachname_alt)
        if cand:
            tok = cand
            source = "nachname_2026-08-07_fullname"
    by = lookup_birth_year(tok)
    if by is None:
        return None, None, None
    age = CURRENT_YEAR - by
    band_start = (age//10)*10
    band = f"{band_start}-{band_start+10}"
    return age, band, source

# ---------- Build a strict (deal, betrag, plz-raw) -> row7 lookup from the
# 2026-08-07 export, so we can pull in its Vorname/Nachname as a *secondary*
# name source without ever mixing up two different customers. Keys that
# collide (multiple candidates - only ~24 out of 9508 rows) are dropped so we
# never guess wrong. ----------
def key7(row):
    return (row["Deal-Name"].strip(), row["Betrag"].strip(), (row.get("Postleitzahl") or "").strip())

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

# ---------- Load & process ----------
rows_out=[]
name_source_count = Counter()

with open(PATH, encoding="utf-8-sig") as f:
    r = csv.DictReader(f)
    for row in r:
        row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        dealname = row["Deal-Name"]
        plz_raw = row["Postleitzahl"]
        vorname = row["Vorname"]
        nachname = row.get("Nachname","")

        datum = row.get("Abschlussdatum – monatlich","")
        def _has_val(v):
            return bool(v) and v != "(Kein Wert)"
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

        row7 = lookup7.get((dealname.strip(), row["Betrag"].strip(), (plz_raw or "").strip()))
        vorname7 = row7.get("Vorname") if row7 else None
        nachname7 = row7.get("Nachname") if row7 else None

        age, ageband, name_source = estimate_age_band(vorname, dealname, vorname7, nachname7)
        if name_source:
            name_source_count[name_source] += 1

        rows_out.append({
            "deal":dealname,"betrag":betrag,"plz":plz,"region":region,
            "vorname":vorname,"nachname":nachname,"age":age,"ageband":ageband,
            "cat":cat,"group":group,"datum":datum,"year":year,"name_source":name_source,
        })

print("Total rows:", len(rows_out))
print("Total Umsatz:", sum(x["betrag"] for x in rows_out))
print("Rows with age estimate:", sum(1 for x in rows_out if x["ageband"]))
print("Rows with region:", sum(1 for x in rows_out if x["region"] and "Unbekannt" not in x["region"]))
print("Name-Quelle für Altersschätzung:", dict(name_source_count))

unresolved = [x for x in rows_out if x["ageband"] is None]
print("Weiterhin unbekanntes Alter:", len(unresolved), "Umsatz:", sum(x["betrag"] for x in unresolved))

catcount = Counter(x["cat"] for x in rows_out)
catrev = defaultdict(float)
for x in rows_out: catrev[x["cat"]] += x["betrag"]
print("\n--- Kategorien (Anzahl / Umsatz) ---")
for k,v in sorted(catcount.items(), key=lambda kv:-catrev[kv[0]]):
    print(f"{k:30s} n={v:5d}  umsatz={catrev[k]:,.0f}")

json.dump(rows_out, open("/tmp/processed_rows.json","w"), ensure_ascii=False)
print("\nsaved /tmp/processed_rows.json")
