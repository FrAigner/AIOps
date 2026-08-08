"""Deterministisches Kontext-Buendel fuer den Chat.

Das kleine lokale Modell (1-3B Parameter) ist bei Tool-Use unzuverlaessig -
deshalb haengt die Grundqualitaet der Antwort nicht davon ab, dass es Tools
korrekt aufruft. Bei jeder Anfrage wird zuerst deterministisch der aktuelle
Zustand der Plattform zusammengetragen (Alarme, SLIs, Dependencies, Chaos-
Szenario) und dem Modell als Text mitgegeben. Tools (siehe tools.py) sind nur
fuer Drill-down gedacht, den das Buendel nicht abdeckt.
"""

from __future__ import annotations

import asyncio
import os

import httpx

VM_URL = os.getenv("VM_URL", "http://victoriametrics:8428")
VMALERT_URL = os.getenv("VMALERT_URL", "http://vmalert:8880")
POC_API_URL = os.getenv("POC_API_URL", "http://poc-api:8000")
STORE_API_URL = os.getenv("STORE_API_URL", "http://store-api:8001")

JOBS = ["poc-api", "store-api"]

SLI_QUERIES = {
    "traffic": 'poc:requests:rate5m{{job="{job}"}}',
    "error_ratio": 'poc:error_ratio:5m{{job="{job}"}}',
    "p95": 'poc:latency_p95:5m{{job="{job}"}}',
    "seasonal_ratio": 'poc:requests:seasonal_ratio{{job="{job}"}}',
    "business_ratio": 'poc:business_txn:seasonal_ratio{{job="{job}"}}',
    "profile_days": 'poc:learning:profile_days{{job="{job}"}}',
}


async def _vm_query(client: httpx.AsyncClient, expr: str) -> list[dict]:
    try:
        r = await client.get(f"{VM_URL}/api/v1/query", params={"query": expr}, timeout=10)
        r.raise_for_status()
        return r.json()["data"]["result"]
    except Exception:
        return []


async def _first_value(client: httpx.AsyncClient, expr: str) -> float | None:
    res = await _vm_query(client, expr)
    if not res:
        return None
    try:
        return float(res[0]["value"][1])
    except (KeyError, ValueError, IndexError):
        return None


async def _alerts(client: httpx.AsyncClient) -> tuple[list[str], list[str]]:
    try:
        r = await client.get(f"{VMALERT_URL}/api/v1/rules", timeout=10)
        r.raise_for_status()
        groups = r.json()["data"]["groups"]
    except Exception:
        return [], []
    firing, pending = [], []
    for g in groups:
        for rule in g.get("rules", []):
            for a in rule.get("alerts", []):
                label = f"{a['labels'].get('alertname')} ({a['labels'].get('job', '?')}"
                extra = a["labels"].get("dependency") or a["labels"].get("http_target")
                if extra:
                    label += f", {extra}"
                label += ")"
                if a["state"] == "firing":
                    firing.append(label)
                elif a["state"] == "pending":
                    pending.append(label)
    return firing, pending


async def _chaos(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(f"{url}/chaos", timeout=5)
        r.raise_for_status()
        d = r.json()
        return d.get("detail", {}).get("label", d.get("active", "unbekannt"))
    except Exception:
        return "nicht abrufbar"


async def _slis_for_job(client: httpx.AsyncClient, job: str) -> dict[str, float | None]:
    keys = list(SLI_QUERIES.keys())
    values = await asyncio.gather(
        *(_first_value(client, tpl.format(job=job)) for tpl in SLI_QUERIES.values())
    )
    return dict(zip(keys, values))


def _fmt(v: float | None, unit: str = "", decimals: int = 2) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{v:.{decimals}f}{unit}"
    except (TypeError, ValueError):
        return "n/a"


async def gather_context() -> str:
    """Baut einen kompakten deutschen Text-Block mit dem aktuellen Systemzustand."""
    async with httpx.AsyncClient() as client:
        (firing, pending), shop_chaos, store_chaos, slis_by_job, dep = await asyncio.gather(
            _alerts(client),
            _chaos(client, POC_API_URL),
            _chaos(client, STORE_API_URL),
            asyncio.gather(*(_slis_for_job(client, job) for job in JOBS)),
            _vm_query(client, 'topk(5, poc:dependency_p95:5m{job="poc-api"})'),
        )

    lines = ["## Aktueller Systemzustand\n"]
    lines.append(f"Aktives Chaos-Szenario Shop (poc-api): {shop_chaos}")
    lines.append(f"Aktives Chaos-Szenario Filiale (store-api): {store_chaos}\n")
    lines.append("Alarme, die JETZT feuern: " + (", ".join(firing) if firing else "keine"))
    lines.append("Alarme im Anlauf (pending): " + (", ".join(pending) if pending else "keine") + "\n")

    for job, s in zip(JOBS, slis_by_job):
        lines.append(f"### {job}")
        lines.append(
            f"- Traffic: {_fmt(s['traffic'])} req/s"
            + (f" ({_fmt((s['seasonal_ratio'] or 0) * 100, ' % der saisonalen Erwartung', 0)})"
               if s['seasonal_ratio'] is not None else "")
        )
        lines.append(f"- Fehlerrate: {_fmt((s['error_ratio'] or 0) * 100 if s['error_ratio'] is not None else None, ' %', 2)}")
        lines.append(f"- P95-Latenz: {_fmt(s['p95'], ' ms', 0)}")
        lines.append(
            "- Geschaeftsvolumen (Bestellungen/Kassenvorgaenge): "
            f"{_fmt((s['business_ratio'] or 0) * 100 if s['business_ratio'] is not None else None, ' % der saisonalen Erwartung', 0)}"
        )
        lines.append(f"- Gelernte Vergleichstage: {_fmt(s['profile_days'], '', 0)}\n")

    if dep:
        lines.append("Top-5 langsamste Downstream-Systeme (Shop, P95 ms):")
        for item in sorted(dep, key=lambda x: -float(x["value"][1])):
            lines.append(f"- {item['metric'].get('dependency', '?')}: {_fmt(float(item['value'][1]), ' ms', 0)}")

    return "\n".join(lines)
