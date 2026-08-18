"""
Zentrale Konfiguration/Secrets-Loader.

Lokal: liest aus einer .env-Datei im Projektroot (nicht ins Git-Repo committen!).
In GitHub Actions: liest aus den Environment-Variablen, die aus den GitHub-Secrets
gesetzt werden (siehe .github/workflows/*.yml und README.md für die vollständige Liste).

Jeder Getter gibt None zurück, wenn das Secret fehlt (kein Crash) -> Jobs/Signale
können dann selbst entscheiden, ob sie "graceful" überspringen oder abbrechen.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def _load_dotenv():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_dotenv()


def get(name: str, default=None):
    return os.environ.get(name, default)


def require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Fehlendes Secret/ENV: {name}. Siehe README.md 'Benötigte Secrets' "
            f"und lege es entweder in .env (lokal) oder als GitHub Actions Secret an."
        )
    return val


def missing(*names) -> list:
    """Gibt die Liste der Namen zurück, die (noch) nicht gesetzt sind."""
    return [n for n in names if not os.environ.get(n)]


# ---- Vollständige Secrets-Registry (Single Source of Truth) ----
# Wird von jobs/api_smoke_test.py genutzt, um den Status jeder Integration zu zeigen.
SECRET_GROUPS = {
    "Google Sheets (Deals)": [
        "GOOGLE_SHEETS_SERVICE_ACCOUNT_JSON",
        "GOOGLE_SHEETS_SPREADSHEET_ID",
    ],
    "Google Ads": [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_CUSTOMER_ID",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    ],
    "Meta Ads": ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"],
    "Google Search Console": ["GSC_SERVICE_ACCOUNT_JSON", "GSC_SITE_URL"],
    "Sistrix": ["SISTRIX_API_KEY", "SISTRIX_DOMAIN"],
    "Notion": [
        "NOTION_TOKEN",
        "NOTION_DB_WEEKLY_NUMBERS",
        "NOTION_DB_TASKS",
        "NOTION_DB_LEARNINGS",
        "NOTION_DB_CONTENT_PLAN",
        "NOTION_DB_ANOMALIES",
    ],
    "Anthropic (KI-Jobs)": ["ANTHROPIC_API_KEY"],
    "Dashboard-Verschlüsselung": ["DASHBOARD_PASSWORD"],
}
