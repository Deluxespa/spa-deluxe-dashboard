"""
Wetter-Signal ohne API-Key: Open-Meteo (https://open-meteo.com) ist kostenlos
und braucht keinen Account. Wir holen eine 16-Tage-Vorhersage für ein paar
repräsentative deutsche Städte (Verteilung ~ Kundenregionen) und aggregieren
eine einfache "Whirlpool-Wetter-Gunst" (kalt/nass = gut für Whirlpool-Kaufinteresse,
laut Team-Erfahrung eher Herbst/Winter-Peak).
"""
import statistics
import urllib.request
import json

# Städte grob proportional zu den Top-Regionen aus den HubSpot-Daten
CITIES = {
    "Berlin": (52.52, 13.405),
    "Hamburg": (53.55, 9.993),
    "Muenchen": (48.137, 11.575),
    "Koeln": (50.937, 6.960),
    "Stuttgart": (48.775, 9.182),
    "Duesseldorf": (51.227, 6.773),
}


def fetch_forecast(days: int = 14) -> dict:
    """Gibt {stadt: {"tmax": [...], "precip": [...]}} zurück. Bei Netzwerkfehler: {}."""
    out = {}
    for city, (lat, lon) in CITIES.items():
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,precipitation_sum"
            f"&forecast_days={min(days, 16)}&timezone=Europe%2FBerlin"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            daily = data.get("daily", {})
            out[city] = {
                "tmax": daily.get("temperature_2m_max", []),
                "precip": daily.get("precipitation_sum", []),
            }
        except Exception as e:
            out[city] = {"error": str(e)}
    return out


def weather_signal(forecast: dict) -> float:
    """Sehr einfache Heuristik -> Signal in [-1, +1].
    Kühlere Temperaturen (< 15°C Durchschnitt) und mehr Regen -> positiv fürs
    Whirlpool/Wellness-Kaufinteresse (Leute planen Rückzug/Erholung zuhause).
    Sehr warmes, trockenes Wetter -> leicht negativ (Urlaubssaison/Garten statt Whirlpool-Kauf).
    Muss mit echten Konversionsdaten kalibriert werden, sobald genug Historie da ist."""
    tmax_all, precip_all = [], []
    for city, d in forecast.items():
        tmax_all += [t for t in d.get("tmax", []) if t is not None]
        precip_all += [p for p in d.get("precip", []) if p is not None]
    if not tmax_all:
        return 0.0
    avg_tmax = statistics.mean(tmax_all)
    avg_precip = statistics.mean(precip_all) if precip_all else 0.0

    temp_component = max(-1.0, min(1.0, (15.0 - avg_tmax) / 15.0))
    precip_component = max(-1.0, min(1.0, avg_precip / 5.0))
    signal = 0.7 * temp_component + 0.3 * precip_component
    return round(max(-1.0, min(1.0, signal)), 3)


def fetch_historical_month(year: int, month: int) -> dict:
    """Historische Monatswerte via Open-Meteo Archive-API (kostenlos, kein Key).
    Gibt {"avg_temp_max":, "avg_temp_min":, "sunshine_hours":, "precipitation_mm":} zurück,
    gemittelt/summiert über alle CITIES-Standorte -> passt exakt ins Original-Schema
    (siehe data/cache/reference_snapdata.json -> "weather")."""
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"

    tmax_all, tmin_all, sun_all, precip_all = [], [], [], []
    for city, (lat, lon) in CITIES.items():
        url = (
            "https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat}&longitude={lon}&start_date={start}&end_date={end}"
            "&daily=temperature_2m_max,temperature_2m_min,sunshine_duration,precipitation_sum"
            "&timezone=Europe%2FBerlin"
        )
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            daily = data.get("daily", {})
            tmax_all += [t for t in daily.get("temperature_2m_max", []) if t is not None]
            tmin_all += [t for t in daily.get("temperature_2m_min", []) if t is not None]
            sun_all += [s for s in daily.get("sunshine_duration", []) if s is not None]
            precip_all += [p for p in daily.get("precipitation_sum", []) if p is not None]
        except Exception:
            continue

    if not tmax_all:
        return {"avg_temp_max": None, "avg_temp_min": None, "sunshine_hours": None, "precipitation_mm": None}

    return {
        "avg_temp_max": round(statistics.mean(tmax_all), 1),
        "avg_temp_min": round(statistics.mean(tmin_all), 1) if tmin_all else None,
        "sunshine_hours": round(sum(sun_all) / len(CITIES) / 3600.0, 1) if sun_all else None,
        "precipitation_mm": round(sum(precip_all) / len(CITIES), 1) if precip_all else None,
    }


if __name__ == "__main__":
    fc = fetch_forecast()
    print(json.dumps(fc, indent=2)[:500])
    print("Signal:", weather_signal(fc))
