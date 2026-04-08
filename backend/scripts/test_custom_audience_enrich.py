#!/usr/bin/env python3
"""
Verifica locale dell'arricchimento nomi Custom Audience nel targeting (senza chiamate Meta reali).

Uso (dalla directory backend):
  python scripts/test_custom_audience_enrich.py

Con Docker (dalla root del repo, richiede immagine backend già buildata):
  docker compose run --rm backend python scripts/test_custom_audience_enrich.py
"""
from __future__ import annotations

import os
import sys

# Settings richiede Google OAuth in .env: per esecuzione standalone senza .env completo
os.environ.setdefault("GOOGLE_CLIENT_ID", "local-test-placeholder")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "local-test-placeholder")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integrations.meta_marketing import MetaMarketingService


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    svc = MetaMarketingService(access_token="fake-token-for-unit-test")

    resolved: dict[str, str] = {
        "120204261878650067": "Ecampus SLD modulo inviato 90gg",
        "999": "Second audience",
    }
    calls: list[str] = []

    def fake_resolve(aid: str) -> str:
        k = str(aid).strip()
        calls.append(k)
        return resolved.get(k, "")

    svc._get_custom_audience_name_cached = fake_resolve  # type: ignore[method-assign]

    # 1) Esclusioni solo id → nome aggiunto
    targeting = {
        "excluded_custom_audiences": [{"id": "120204261878650067"}],
        "custom_audiences": [{"id": "999", "name": ""}],
    }
    out = svc.enrich_targeting_custom_audience_names(targeting)
    ex = out.get("excluded_custom_audiences") or []
    if not ex or ex[0].get("name") != resolved["120204261878650067"]:
        return _fail(f"excluded_custom_audiences: atteso nome risolto, got {ex!r}")
    inc = out.get("custom_audiences") or []
    if not inc or inc[0].get("name") != resolved["999"]:
        return _fail(f"custom_audiences senza name: atteso fill, got {inc!r}")

    # 2) Non modifica l'originale (deep copy)
    if targeting["excluded_custom_audiences"][0].get("name"):
        return _fail("il dict originale non deve essere mutato")

    # 3) Name già presente → nessuna nuova risoluzione per quell'elemento
    calls.clear()
    svc._custom_audience_name_cache.clear()
    out2 = svc.enrich_targeting_custom_audience_names(
        {
            "excluded_custom_audiences": [
                {"id": "120204261878650067", "name": "Già noto"},
            ]
        }
    )
    if calls:
        return _fail(f"con name già valorizzato non deve chiamare resolve, calls={calls}")
    if (out2.get("excluded_custom_audiences") or [{}])[0].get("name") != "Già noto":
        return _fail("name esistente deve restare")

    # 4) flexible_spec + exclusions
    calls.clear()
    flex_in = {
        "flexible_spec": [
            {
                "exclusions": {
                    "excluded_custom_audiences": [{"id": "999"}],
                }
            }
        ]
    }
    out3 = svc.enrich_targeting_custom_audience_names(flex_in)
    flex = out3.get("flexible_spec") or []
    nested = (flex[0].get("exclusions") or {}).get("excluded_custom_audiences") or []
    if nested[0].get("name") != resolved["999"]:
        return _fail(f"flexible_spec exclusions: got {nested!r}")

    # 5) Stesso ID ripetuto: cache → un solo CustomAudience(...) reale (mock del costruttore)
    from unittest import mock

    svc2 = MetaMarketingService(access_token="fake-token")
    svc2._custom_audience_name_cache.clear()
    ca_construct_calls: list[str] = []

    def _make_mock_audience(_aid: str):
        ca_construct_calls.append(str(_aid))
        m = mock.Mock()
        m.export_all_data = lambda: {"name": "FromAPI"}
        return m

    with mock.patch.object(svc2, "_make_api_call_with_retry", side_effect=lambda fn: fn()):
        with mock.patch(
            "services.integrations.meta_marketing.CustomAudience",
            side_effect=_make_mock_audience,
        ):
            out5 = svc2.enrich_targeting_custom_audience_names(
                {
                    "excluded_custom_audiences": [
                        {"id": "111"},
                        {"id": "111"},
                    ],
                }
            )
    if ca_construct_calls != ["111"]:
        return _fail(f"cache stesso id: atteso un solo construct, got {ca_construct_calls!r}")
    rows5 = out5.get("excluded_custom_audiences") or []
    if len(rows5) != 2 or not all(r.get("name") == "FromAPI" for r in rows5):
        return _fail(f"due righe stesso id devono avere name: {rows5!r}")

    # Riepilogo ID visti dal codice di enrich (dati fittizi: nessuna chiamata Graph reale)
    print("")
    print("ID ricavati dal JSON targeting (scenario 1–4, resolver mock):")
    print(f"  - {ex[0].get('id')} → name: {ex[0].get('name')!r}")
    print(f"  - {inc[0].get('id')} → name: {inc[0].get('name')!r}")
    print(f"  - {nested[0].get('id')} (flexible_spec exclusions) → name: {nested[0].get('name')!r}")
    print("ID ricavati (scenario 5, CustomAudience mock + cache):")
    print(f"  - {rows5[0].get('id')} (ripetuto 2 volte in lista) → costruttore CA chiamato: {ca_construct_calls!r}")
    print(f"  - name assegnato alle due righe: {rows5[0].get('name')!r}")
    print("")
    print("OK: enrich custom_audiences / excluded_custom_audiences (mock + cache smoke)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
