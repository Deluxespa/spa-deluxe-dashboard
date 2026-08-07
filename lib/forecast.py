"""
6-Signal-Ensemble-Forecast-Modell für den Monatsabschluss (analog zum Original-Tool):

  1. Pacing        – Wie viel Umsatz/Deals sind bereits im laufenden Monat reingekommen,
                      hochgerechnet auf Basis der bisherigen Tagesrate vs. Vormonate.
  2. Saisonalitaet  – Historischer Saisonfaktor pro Kalendermonat (z.B. Whirlpool-Käufe
                      im Herbst/Winter höher) aus den Vorjahresdaten.
  3. Wetter         – 14-Tage-Wettervorhersage (Open-Meteo, kein Key nötig), siehe weather_client.py.
  4. SEO            – Sichtbarkeits-/Rankingtrend (Sistrix). Ohne API-Key: Signal=None -> wird
                      beim Ensemble übersprungen und die übrigen Gewichte werden renormiert.
  5. Ads-Effizienz  – CPL/CPC-Trend aus Google Ads + Meta Ads der letzten 2 Wochen vs. Vormonat.
                      Ohne API-Zugang: Signal=None -> übersprungen.
  6. Sales-Cycle    – Durchschnittliche Zeit von Lead bis Deal-Win (aus HubSpot-Historie),
                      um zu schätzen wie viele der *aktuellen* Leads noch in diesem Monat
                      konvertieren vs. erst im Folgemonat.

Jedes Signal liefert einen Wert in [-1, +1] (negativ = Gegenwind, positiv = Rückenwind)
ODER None, wenn die Datenquelle (noch) nicht angebunden ist. Das Ensemble gewichtet nur
die tatsächlich verfügbaren Signale (Gewichte werden renormiert), damit das Modell schon
JETZT nutzbar ist und nicht auf alle 6 Datenquellen warten muss.
"""
from dataclasses import dataclass, field
from typing import Optional

# Basis-Gewichte, wenn ALLE 6 Signale verfügbar sind. Diese Werte sind ein
# sinnvoller Startpunkt und sollten kalibriert werden, sobald genug Monate
# an tatsächlichem Forecast-vs-Ist-Historie vorliegen (siehe jobs/forecast_month_end.py).
BASE_WEIGHTS = {
    "pacing": 0.30,
    "saisonalitaet": 0.20,
    "wetter": 0.10,
    "seo": 0.15,
    "ads_effizienz": 0.15,
    "sales_cycle": 0.10,
}


@dataclass
class Signal:
    name: str
    value: Optional[float]  # None = Datenquelle nicht verfügbar
    note: str = ""


@dataclass
class ForecastResult:
    signals: list = field(default_factory=list)
    combined_score: float = 0.0  # gewichteter Score in [-1, +1]
    used_weight_sum: float = 0.0
    missing: list = field(default_factory=list)
    projection_pct: float = 0.0  # z.B. +8.3 heisst "+8.3% ggü. linearer Pacing-Projektion"

    def as_dict(self):
        return {
            "signals": [s.__dict__ for s in self.signals],
            "combined_score": self.combined_score,
            "used_weight_sum": self.used_weight_sum,
            "missing": self.missing,
            "projection_pct": self.projection_pct,
        }


def pacing_signal(mtd_umsatz: float, vormonate_gleicher_tag: list) -> Signal:
    """mtd_umsatz: Umsatz von Monatsbeginn bis heute (aktueller Monat).
    vormonate_gleicher_tag: Liste von Umsätzen der letzten N Monate, jeweils
    bis zum GLEICHEN Kalendertag gerechnet (fairer Vergleich)."""
    if not vormonate_gleicher_tag:
        return Signal("pacing", None, "keine Vergleichsmonate")
    avg_vorjahre = sum(vormonate_gleicher_tag) / len(vormonate_gleicher_tag)
    if avg_vorjahre <= 0:
        return Signal("pacing", None, "Vergleichsbasis 0")
    delta = (mtd_umsatz - avg_vorjahre) / avg_vorjahre
    val = max(-1.0, min(1.0, delta))
    return Signal("pacing", round(val, 3), f"MTD {mtd_umsatz:.0f} vs Ø Vorperiode {avg_vorjahre:.0f}")


def saisonalitaet_signal(monat: int, saison_index_by_month: dict) -> Signal:
    """saison_index_by_month: {1: 0.8, 2: 0.9, ..., 12: 1.4} -> 1.0 = Durchschnittsmonat.
    Wird aus den Vorjahres-Umsätzen pro Kalendermonat berechnet (siehe jobs)."""
    idx = saison_index_by_month.get(monat)
    if idx is None:
        return Signal("saisonalitaet", None, "keine Vorjahresdaten für diesen Monat")
    val = max(-1.0, min(1.0, (idx - 1.0)))
    return Signal("saisonalitaet", round(val, 3), f"Saisonindex Monat {monat}: {idx:.2f}")


def wetter_signal(value: Optional[float]) -> Signal:
    if value is None:
        return Signal("wetter", None, "Open-Meteo nicht erreichbar")
    return Signal("wetter", round(value, 3), "14-Tage-Vorhersage (Open-Meteo)")


def seo_signal(sistrix_visibility_delta_pct: Optional[float]) -> Signal:
    if sistrix_visibility_delta_pct is None:
        return Signal("seo", None, "SISTRIX_API_KEY fehlt – Signal wird übersprungen")
    val = max(-1.0, min(1.0, sistrix_visibility_delta_pct / 20.0))
    return Signal("seo", round(val, 3), f"Sichtbarkeitsindex Δ {sistrix_visibility_delta_pct:+.1f}%")


def ads_effizienz_signal(cpl_delta_pct: Optional[float]) -> Signal:
    """cpl_delta_pct: Veränderung Cost-per-Lead ggü. Vormonat. Sinkender CPL = positiv."""
    if cpl_delta_pct is None:
        return Signal("ads_effizienz", None, "Google/Meta Ads API nicht verbunden – Signal wird übersprungen")
    val = max(-1.0, min(1.0, -cpl_delta_pct / 25.0))
    return Signal("ads_effizienz", round(val, 3), f"CPL Δ {cpl_delta_pct:+.1f}%")


def sales_cycle_signal(offene_leads_juenger_als_zyklus: int, offene_leads_gesamt: int) -> Signal:
    if not offene_leads_gesamt:
        return Signal("sales_cycle", None, "keine offenen Leads")
    anteil = offene_leads_juenger_als_zyklus / offene_leads_gesamt
    val = max(-1.0, min(1.0, (anteil - 0.5) * 2))
    return Signal("sales_cycle", round(val, 3), f"{offene_leads_juenger_als_zyklus}/{offene_leads_gesamt} Leads im Zyklusfenster")


def combine(signals: list, weights: dict = None) -> ForecastResult:
    weights = weights or BASE_WEIGHTS
    available = [s for s in signals if s.value is not None]
    missing = [s.name for s in signals if s.value is None]
    used_weight_sum = sum(weights.get(s.name, 0) for s in available)
    if used_weight_sum <= 0:
        return ForecastResult(signals=signals, combined_score=0.0, used_weight_sum=0.0, missing=missing)
    combined = sum(weights.get(s.name, 0) * s.value for s in available) / used_weight_sum
    return ForecastResult(
        signals=signals,
        combined_score=round(combined, 3),
        used_weight_sum=round(used_weight_sum, 3),
        missing=missing,
        projection_pct=round(combined * 15.0, 2),  # combined_score=+1 -> grob "+15% Projektion", Startannahme
    )


if __name__ == "__main__":
    sigs = [
        pacing_signal(45000, [38000, 41000, 39500]),
        saisonalitaet_signal(11, {11: 1.35}),
        wetter_signal(-0.5),
        seo_signal(None),
        ads_effizienz_signal(None),
        sales_cycle_signal(30, 50),
    ]
    result = combine(sigs)
    import json
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
