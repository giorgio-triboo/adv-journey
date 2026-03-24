"""
Periodo effettivo per sync RCRM Ulixe (solo stdlib: importabile per test senza Google/SQLAlchemy).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_ROME_TZ = ZoneInfo("Europe/Rome")


def resolve_ulixe_rcrm_sync_period(
    requested_period: str,
    *,
    now: datetime | None = None,
) -> tuple[str, bool]:
    """
    Regola operativa: il 1° giorno del mese (fuso Europe/Rome), se il periodo richiesto
    coincide con il mese calendario corrente, si usa il mese precedente.

    Il tab Google (es. {mm}-ulixe-rcrm) e i record in ulixe_rcrm_temp si riferiscono così
    al mese appena chiuso: es. 1° aprile con richiesta 2026-04 → effettivo 2026-03.

    Se l'utente richiede esplicitamente un mese diverso dal mese corrente (es. 1° aprile
    e periodo 2026-03), non si modifica nulla.
    """
    rp = (requested_period or "").strip()
    if not rp:
        return rp, False

    now = now or datetime.now(_ROME_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_ROME_TZ)
    else:
        now = now.astimezone(_ROME_TZ)

    if now.day != 1:
        return rp, False

    current_period = f"{now.year}-{now.month:02d}"
    if rp != current_period:
        return rp, False

    first = datetime(now.year, now.month, 1, tzinfo=_ROME_TZ)
    prev = first - timedelta(days=1)
    effective = f"{prev.year}-{prev.month:02d}"
    return effective, True
