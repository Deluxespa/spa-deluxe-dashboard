"""
Zeigt fuer jede Integration (HubSpot, Google Ads, Meta, GSC, Sistrix, Notion, ...)
an, ob die noetigen Secrets/ENV-Variablen gesetzt sind - ohne echte API-Calls
zu machen. Nuetzlich direkt nach dem Anlegen von .env oder den GitHub Secrets,
um Tippfehler/fehlende Werte schnell zu finden.

Aufruf:  python3 jobs/api_smoke_test.py
Exit-Code 0 = alles gesetzt, 1 = mindestens eine Gruppe unvollstaendig.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib import config  # noqa: E402


def main() -> int:
    print("Secrets-Check (liest .env lokal bzw. ENV-Variablen in CI)\n")
    all_ok = True
    for group, names in config.SECRET_GROUPS.items():
        fehlend = config.missing(*names)
        status = "OK" if not fehlend else "FEHLT"
        marker = "[x]" if not fehlend else "[ ]"
        print(f"{marker} {group}: {status}")
        if fehlend:
            all_ok = False
            for n in fehlend:
                print(f"      - {n}")
    print()
    if all_ok:
        print("Alle bekannten Secret-Gruppen sind vollstaendig gesetzt.")
    else:
        print(
            "Mindestens eine Gruppe ist unvollstaendig. Fehlende Integrationen "
            "werden von den Jobs automatisch uebersprungen (kein Crash), liefern "
            "aber keine Daten/Signale fuer diesen Bereich. Siehe README.md."
        )
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
