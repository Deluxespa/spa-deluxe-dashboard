#!/usr/bin/env python3
"""
Haupt-Job "weekly-numbers-update" (analog zum Original-System):

1. Lädt die Deal-Daten live aus einem Google Sheet (siehe lib/gsheet_processing.py),
   das per Zoho-Automatisierung/Zapier/Make mit den gewonnenen Deals befüllt wird.
   Sind die Google-Sheets-Secrets nicht gesetzt oder schlägt der Live-Pull fehl,
   wird auf den letzten lokalen Cache-Stand zurückgefallen (siehe load_deal_rows()
   unten).
2. Aggregiert pro Kalendermonat: deals_won, revenue, wpk (Wert pro Kunde).
3. Holt echtes Wetter (historisch für vergangene Monate, 14-Tage-Vorhersage
   für den laufenden Monat) via Open-Meteo – kein API-Key nötig.
4. Berechnet das 6-Signal-Forecast-Ensemble für den laufenden ("live") Monat.
5. Schreibt data/cache/snapdata.json im IDENTISCHEN Schema wie das Original-Tool.
6. Rendert dashboard/template/index.html mit den echten Daten, verschlüsselt
   das Ergebnis (AES-256-GCM, Passwort aus DASHBOARD_PASSWORD) und schreibt
   die fertige Gate-Seite nach dashboard/index.html (= GitHub Pages Root).

WICHTIG: dashboard/index.html enthält NUR den verschlüsselten Blob – die Klartext-
Kundendaten (Namen, Beträge, PLZ) landen NIE unverschlüsselt im Git-Repo.
"""
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib import config, forecast, weather_client, crypto, gsheet_processing, zoho_drive_import, google_ads_report  # noqa: E402

PROCESSED_ROWS = ROOT / "data" / "cache" / "processed_rows.json"
SNAPDATA_PATH = ROOT / "data" / "cache" / "snapdata.json"
TEMPLATE_PATH = ROOT / "dashboard" / "template" / "index.html"
OUTPUT_PATH = ROOT / "dashboard" / "index.html"
LOCAL_PREVIEW_PATH = ROOT / "dashboard" / "_local_preview.html"


def fetch_zoho_drive_bundle() -> Optional[dict]:
    """Einmaliger Abruf des jeweils neuesten Zoho-CRM-Drive-Exports (3 Dateien:
    Top-Tier-Leads, Social-Media-Leads, Abschluesse - siehe Ordner
    'Zoho CRM Exporte' und lib/zoho_drive_import.py). Wird sowohl fuer
    zusaetzliche Deal-Rows als auch fuer die Lead-Zahlen-Kennzahl im Dashboard
    verwendet (ein API-Roundtrip statt zwei). None bei fehlenden Secrets oder
    Fehlern (Drive-API/Freigabe) - der Job laeuft dann normal mit den
    Google-Sheet-Deals weiter, nur ohne die Zoho-Drive-Ergaenzung."""
    if config.missing("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"):
        return None
    try:
        result = zoho_drive_import.fetch_latest_zoho_exports()
    except Exception as e:  # noqa: BLE001
        print(f"WARNUNG: Zoho-Drive-Import fehlgeschlagen ({e}).")
        return None
    if result.get("error"):
        print(f"WARNUNG: Zoho-Drive-Import fehlgeschlagen ({result['error']}).")
        return None
    return result


def fetch_google_ads_report_safe() -> Optional[dict]:
    """Einmaliger Abruf des "Google Ads Wochenbericht"-Sheets (Ausgaben +
    Kampagnen, siehe lib/google_ads_report.py). Wird jeden Montag zusammen
    mit dem Zoho-Drive-Import mitgezogen. None bei fehlenden Secrets oder
    Fehlern (Sheet nicht freigegeben o.ä.) - der Job laeuft dann normal
    weiter, nur ohne live verbundenen Ads-Spend/MER."""
    if config.missing("GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON"):
        return None
    result = google_ads_report.fetch_google_ads_report()
    if result.get("error"):
        print(f"WARNUNG: Google-Ads-Wochenbericht-Import fehlgeschlagen ({result['error']}).")
        return None
    return result


def merge_deal_rows(base_rows: list, extra_rows: list) -> list:
    """Ergaenzt base_rows (aus dem Google Sheet) um extra_rows (z.B. aus dem
    Zoho-Drive-Abschluesse-Export), ohne offensichtliche Duplikate doppelt zu
    zaehlen (gleicher Deal-Name + Betrag + Abschlussdatum)."""
    def _key(r):
        return (
            (r.get("deal") or "").strip().lower(),
            round(float(r.get("betrag") or 0), 2),
            r.get("datum"),
        )

    seen = {_key(r) for r in base_rows}
    merged = list(base_rows)
    added, skipped = 0, 0
    for r in extra_rows:
        k = _key(r)
        if k in seen:
            skipped += 1
            continue
        seen.add(k)
        merged.append(r)
        added += 1
    if added or skipped:
        print(f"Zoho-Drive-Merge: {added} neue Deals hinzugefuegt, {skipped} Duplikate uebersprungen.")
    return merged


def load_deal_rows(zoho_drive: Optional[dict] = None) -> list:
    """Holt die Deal-Rows live aus dem Google Sheet (Secrets
    GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON/GOOGLE_SHEETS_SPREADSHEET_ID), cached
    sie danach lokal fuer den Fallback-Fall. Sind die Secrets nicht gesetzt
    (z.B. lokale Entwicklung), wird der letzte Cache-Stand verwendet.
    Ist zoho_drive gesetzt (siehe fetch_zoho_drive_bundle()), werden zusaetzlich
    die Deals aus dem Abschluesse-Export gemergt (dedupliziert)."""
    has_gsheet_creds = not config.missing(
        "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEETS_SPREADSHEET_ID"
    )
    rows = None
    if has_gsheet_creds:
        try:
            rows = gsheet_processing.fetch_live_processed_rows()
            print(f"Google Sheet live: {len(rows)} gewonnene Deals gezogen.")
            PROCESSED_ROWS.parent.mkdir(parents=True, exist_ok=True)
            PROCESSED_ROWS.write_text(
                json.dumps(rows, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:  # noqa: BLE001 - harter Fallback auf Cache
            print(f"WARNUNG: Google-Sheets Live-Pull fehlgeschlagen ({e}). "
                  f"Nutze letzten Cache-Stand, falls vorhanden.")

    if rows is None:
        if not PROCESSED_ROWS.exists():
            raise SystemExit(
                f"Keine Deal-Daten gefunden unter {PROCESSED_ROWS} und keine "
                f"GOOGLE_SHEETS_* Secrets gesetzt bzw. Live-Pull fehlgeschlagen."
            )
        rows = json.loads(PROCESSED_ROWS.read_text(encoding="utf-8"))

    if zoho_drive:
        extra = zoho_drive_import.abschluesse_to_processed_rows(zoho_drive.get("abschluesse", []))
        print(f"Zoho-Drive (Abschluesse-Export): {len(extra)} Deals gezogen.")
        rows = merge_deal_rows(rows, extra)

    return rows


def month_key(datum: str) -> str:
    # datum ist "YYYY-MM-DD"
    return datum[:7]


def aggregate_by_month(rows: list) -> dict:
    by_month = defaultdict(list)
    for r in rows:
        d = r.get("datum")
        if not d:
            continue
        by_month[month_key(d)].append(r)

    result = {}
    for mk, deal_rows in by_month.items():
        revenue = sum(float(r.get("betrag") or 0) for r in deal_rows)
        deals_won = len(deal_rows)
        result[mk] = {
            "deals_won": deals_won,
            "revenue": round(revenue, 2),
            "wpk": round(revenue / deals_won, 2) if deals_won else 0.0,
        }
    return result


def is_past_month(mk: str, today: date) -> bool:
    y, m = int(mk[:4]), int(mk[5:7])
    if y < today.year or (y == today.year and m < today.month):
        return True
    return False


def build_seasonal_index(monthly_agg: dict) -> dict:
    """Saisonindex je Kalendermonat (1-12) aus ALLEN verfügbaren Jahren:
    Umsatz des Monats / Durchschnittsumsatz über alle Monate desselben Jahres."""
    by_year = defaultdict(dict)
    for mk, agg in monthly_agg.items():
        y, m = int(mk[:4]), int(mk[5:7])
        by_year[y][m] = agg["revenue"]

    idx_samples = defaultdict(list)
    for y, months in by_year.items():
        vals = list(months.values())
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        if avg <= 0:
            continue
        for m, rev in months.items():
            idx_samples[m].append(rev / avg)

    return {m: round(sum(vs) / len(vs), 3) for m, vs in idx_samples.items() if vs}


def _linreg_slope(pairs: list) -> Optional[float]:
    """Einfache Least-Squares-Steigung y = slope*x + b über (x, y)-Paare.
    None, wenn zu wenige Punkte oder keine Streuung in x (Division durch 0)."""
    pts = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pts) < 3:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xbar = sum(xs) / len(xs)
    ybar = sum(ys) / len(ys)
    num = sum((x - xbar) * (y - ybar) for x, y in pts)
    den = sum((x - xbar) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


def build_weather_detail(y: int, m: int, wetter_fc: dict, weather_deals_pairs: list) -> dict:
    """Zusätzliche, für die Dashboard-Karte "Wetter-Signal" aufbereitete Werte:
    aktuelle Ø Vorhersage-Temperatur, Ø Temperatur im selben Monat letztes Jahr
    (echte Open-Meteo-Archivdaten), Delta, sowie eine aus der bisherigen
    Monatshistorie (Temperatur vs. Deals) real berechnete Sensitivität
    ("X Deals pro °C"). Liefert überall None, wo (noch) nicht genug Daten da
    sind - das Frontend zeigt dann "–" statt erfundener Zahlen."""
    avg_temp_current = weather_client.avg_forecast_tmax(wetter_fc)

    prior_year = y - 1
    prior_hist = weather_client.fetch_historical_month(prior_year, m)
    avg_temp_prior_year = prior_hist.get("avg_temp_max")

    delta_temp = None
    if avg_temp_current is not None and avg_temp_prior_year is not None:
        delta_temp = round(avg_temp_current - avg_temp_prior_year, 1)

    n_months = len([p for p in weather_deals_pairs if p[0] is not None and p[1] is not None])
    sensitivity = _linreg_slope(weather_deals_pairs)

    delta_deals = None
    if delta_temp is not None and sensitivity is not None:
        delta_deals = round(delta_temp * sensitivity)

    return {
        "avg_temp_current": avg_temp_current,
        "avg_temp_prior_year": avg_temp_prior_year,
        "delta_temp": delta_temp,
        "sensitivity_deals_per_c": round(sensitivity, 2) if sensitivity is not None else None,
        "delta_deals": delta_deals,
        "n_months": n_months,
    }


def build_forecast_block(mk: str, monthly_agg: dict, seasonal_idx: dict, weather_deals_pairs: list = None) -> dict:
    y, m = int(mk[:4]), int(mk[5:7])

    # Pacing: bisheriger Umsatz in diesem Monat vs. Ø der letzten bis zu 3 Vormonate
    sorted_prev = sorted([k for k in monthly_agg if k < mk], reverse=True)[:3]
    prev_revenues = [monthly_agg[k]["revenue"] for k in sorted_prev]
    mtd_revenue = monthly_agg.get(mk, {}).get("revenue", 0.0)
    pacing = forecast.pacing_signal(mtd_revenue, prev_revenues)

    saisonal = forecast.saisonalitaet_signal(m, seasonal_idx)

    wetter_fc = weather_client.fetch_forecast()
    wetter = forecast.wetter_signal(weather_client.weather_signal(wetter_fc))
    weather_detail = build_weather_detail(y, m, wetter_fc, weather_deals_pairs or [])

    seo = forecast.seo_signal(None)  # TODO: SISTRIX_API_KEY
    ads = forecast.ads_effizienz_signal(None)  # TODO: Google/Meta Ads API
    sales_cycle = forecast.sales_cycle_signal(0, 0)  # TODO: Zoho Lead-Stage-Timestamps

    signals = [pacing, saisonal, wetter, seo, ads, sales_cycle]
    result = forecast.combine(signals)

    avg_prev_deals = None
    prev_deals = [monthly_agg[k]["deals_won"] for k in sorted_prev]
    if prev_deals:
        avg_prev_deals = sum(prev_deals) / len(prev_deals)

    projected_deals = None
    if avg_prev_deals is not None:
        projected_deals = round(avg_prev_deals * (1 + result.combined_score * 0.15))

    return {
        "deals": projected_deals,
        "revenue": round(mtd_revenue * (1 + result.combined_score * 0.15), 2) if mtd_revenue else None,
        "signals": {s.name: {"value": s.value, "note": s.note} for s in signals},
        "weights_used": forecast.BASE_WEIGHTS,
        "combined_score": result.combined_score,
        "missing_signals": result.missing,
        "weather_detail": weather_detail,
    }


def load_existing_snap() -> dict:
    if SNAPDATA_PATH.exists():
        try:
            return json.loads(SNAPDATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def build_snapdata(rows: list, ads: Optional[dict] = None) -> dict:
    today = date.today()
    monthly_agg = aggregate_by_month(rows)
    seasonal_idx = build_seasonal_index(monthly_agg)
    existing = load_existing_snap()
    current_mk = today.strftime("%Y-%m")

    snap = {}
    weather_deals_pairs = []  # (avg_temp_max, deals_won) je abgeschlossenem Monat -> Basis fuer Wetter-Sensitivitaet
    for mk, agg in sorted(monthly_agg.items()):
        y, m = int(mk[:4]), int(mk[5:7])
        past = is_past_month(mk, today)
        # Historisches Wetter ändert sich nicht mehr -> aus Cache wiederverwenden,
        # falls für diesen (abgeschlossenen) Monat schon vorhanden. Spart bei jedem
        # Lauf ~300 Open-Meteo-Requests fuer bereits final abgerechnete Monate.
        cached = existing.get(mk, {})
        if past and cached.get("status") == "final" and cached.get("weather"):
            weather = cached["weather"]
        else:
            weather = weather_client.fetch_historical_month(y, m) if past else None
        if past and weather:
            weather_deals_pairs.append((weather.get("avg_temp_max"), agg["deals_won"]))
        # Google-Ads-Wochenbericht-Sheet liefert nur "aktueller Monat" + YTD,
        # keine Aufschluesselung nach vergangenen Einzelmonaten -> nur fuer
        # den laufenden Monat live setzen, vergangene Monate bleiben None.
        google_ads_spend = ads.get("spend_current_month_eur") if (ads and mk == current_mk) else None
        meta_perf_spend = None  # TODO: META_* Secrets (noch nicht angebunden)
        brand_spend = None
        # total_spend nur setzen, wenn wir mind. eine echte Spend-Quelle haben,
        # sonst weiter ehrlich None statt Fantasiezahlen. Sobald Meta/Brand
        # angebunden sind, hier einfach += ergaenzen.
        total_spend = google_ads_spend if google_ads_spend is not None else None
        entry = {
            "month": mk,
            "status": "final" if past else "live",
            "google_ads_spend": google_ads_spend,
            "meta_perf_spend": meta_perf_spend,  # TODO: META_* Secrets
            "brand_spend": brand_spend,
            "total_spend": total_spend,
            "deals_won": agg["deals_won"],
            "revenue": agg["revenue"],
            "wpk": agg["wpk"],
            "sistrix_si": None,         # TODO: SISTRIX_API_KEY
            "gsc": {},                  # TODO: GSC_SERVICE_ACCOUNT_JSON
            "weather": weather,
            "saved_at": today.isoformat(),
        }
        if not past and ads and mk == current_mk:
            entry["google_ads_spend_ytd"] = ads.get("spend_ytd_eur")
            entry["google_ads_account"] = ads.get("account")
            entry["google_ads_stand"] = ads.get("stand")
            entry["google_ads_top_campaigns"] = (ads.get("campaigns") or [])[:15]
        if not past:
            entry["forecast"] = build_forecast_block(mk, monthly_agg, seasonal_idx, weather_deals_pairs)
        snap[mk] = entry
    return snap


MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def build_hero_block(snap: dict, leads: Optional[dict], today: date) -> dict:
    """Baut die Daten fuer die "MER Tracking"-Hero-Karte (oberste Karte im
    Dashboard). Umsatz/Verkaeufe kommen aus dem live berechneten snap[] fuer
    den laufenden Monat, Leads+CR aus dem Zoho-Drive-Lead-Export. Google-Ads-
    Spend kommt seit dem "Google Ads Wochenbericht"-Sheet live mit (siehe
    lib/google_ads_report.py + build_snapdata()); Meta-Ads/Brand-Spend sind
    (noch) NICHT verbunden (kein API-Zugang) -> total_spend/MER basieren
    aktuell nur auf Google Ads, Template zeigt das transparent an, bis auch
    Meta/Brand angebunden sind (siehe Prinzip: erst live bekommen, dann
    Schritt fuer Schritt korrekt/vollstaendig machen).
    """
    import calendar

    current_mk = today.strftime("%Y-%m")
    entry = snap.get(current_mk, {})
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    pacing_pct = round(today.day / days_in_month * 100, 1)

    revenue = entry.get("revenue")
    deals_won = entry.get("deals_won")
    total_spend = entry.get("total_spend")
    mer = round(revenue / total_spend, 2) if revenue is not None and total_spend else None

    # Welche Spend-Quellen stecken aktuell in total_spend? Fuer eine ehrliche
    # Anzeige im Template (z.B. "Google Ads (Meta + Brand folgen)"), solange
    # noch nicht alle drei Quellen live angebunden sind.
    spend_sources = []
    if entry.get("google_ads_spend") is not None:
        spend_sources.append("google_ads")
    if entry.get("meta_perf_spend") is not None:
        spend_sources.append("meta_perf")
    if entry.get("brand_spend") is not None:
        spend_sources.append("brand")

    leads_total = None
    if leads:
        top = (leads.get("top_tier") or {}).get("gesamt")
        sm = (leads.get("sm_leads") or {}).get("gesamt")
        parts = [v for v in (top, sm) if isinstance(v, (int, float))]
        if parts:
            leads_total = sum(parts)
    cr_pct = round(deals_won / leads_total * 100, 1) if leads_total and deals_won is not None else None

    return {
        "month_label": f"{MONTHS_DE[today.month - 1]} {today.year}",
        "day_of_month": today.day,
        "days_in_month": days_in_month,
        "pacing_pct": pacing_pct,
        "revenue": revenue,
        "deals_won": deals_won,
        "leads_total": leads_total,
        "cr_pct": cr_pct,
        "total_spend": total_spend,
        "spend_sources": spend_sources,
        "mer": mer,
        "generated_at": today.isoformat(),
    }


def render_and_encrypt(snap: dict, leads: Optional[dict] = None, hero: Optional[dict] = None):
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    import re

    snap_json = json.dumps(snap, ensure_ascii=False)
    new_html = re.sub(
        r'(<script id="snapData"[^>]*>)(.*?)(</script>)',
        lambda m: m.group(1) + snap_json + m.group(3),
        html,
        flags=re.S,
    )

    leads_json = json.dumps(leads or {}, ensure_ascii=False)
    new_html = re.sub(
        r'(<script id="leadsData"[^>]*>)(.*?)(</script>)',
        lambda m: m.group(1) + leads_json + m.group(3),
        new_html,
        flags=re.S,
    )

    hero_json = json.dumps(hero or {}, ensure_ascii=False)
    new_html = re.sub(
        r'(<script id="heroData"[^>]*>)(.*?)(</script>)',
        lambda m: m.group(1) + hero_json + m.group(3),
        new_html,
        flags=re.S,
    )

    LOCAL_PREVIEW_PATH.write_text(new_html, encoding="utf-8")
    print(f"Lokale Klartext-Vorschau (NICHT committen!): {LOCAL_PREVIEW_PATH}")

    password = config.get("DASHBOARD_PASSWORD")
    if not password:
        print(
            "WARNUNG: DASHBOARD_PASSWORD nicht gesetzt – dashboard/index.html wird "
            "NICHT neu geschrieben, um kein unverschlüsseltes Ergebnis zu committen. "
            "Setze DASHBOARD_PASSWORD in .env oder als GitHub Secret."
        )
        return

    enc = crypto.encrypt_html(new_html, password)
    gate_html = crypto.build_gate_html(enc)
    OUTPUT_PATH.write_text(gate_html, encoding="utf-8")
    print(f"Verschlüsseltes Dashboard geschrieben: {OUTPUT_PATH}")


def main():
    zoho_drive = fetch_zoho_drive_bundle()
    rows = load_deal_rows(zoho_drive)
    ads = fetch_google_ads_report_safe()
    snap = build_snapdata(rows, ads)
    SNAPDATA_PATH.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"snapdata.json aktualisiert: {SNAPDATA_PATH} ({len(snap)} Monate)")

    leads = None
    if zoho_drive:
        leads = {
            "top_tier": zoho_drive.get("top_tier"),
            "sm_leads": zoho_drive.get("sm_leads"),
            "files_used": {
                k: v for k, v in zoho_drive.get("files_used", {}).items()
                if k in ("top_tier", "sm_leads")
            },
        }

    hero = build_hero_block(snap, leads, date.today())
    render_and_encrypt(snap, leads, hero)


if __name__ == "__main__":
    main()
