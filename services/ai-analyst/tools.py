"""Drill-down-Tools fuer das Chat-Modell.

Bewusst nur drei, klar abgegrenzte Tools - je mehr Auswahl, desto haeufiger
ruft ein kleines Modell das falsche oder gar keines auf. Jede Funktion faengt
ihre eigenen Fehler ab und gibt einen Text zurueck statt zu werfen, weil ein
Tool-Fehler die Antwort nicht abreissen lassen soll.
"""

from __future__ import annotations

import os

import httpx

VM_URL = os.getenv("VM_URL", "http://victoriametrics:8428")
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100")
TEMPO_URL = os.getenv("TEMPO_URL", "http://tempo:3200")
GRAFANA_URL = os.getenv("GRAFANA_URL", "http://grafana:3000")
# Fuer Links, die im Chat angezeigt werden - muss vom Browser des Nutzers aus
# erreichbar sein, im Gegensatz zu GRAFANA_URL (nur im Docker-Netz aufloesbar).
GRAFANA_PUBLIC_URL = os.getenv("GRAFANA_PUBLIC_URL", "http://localhost:3000")

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_promql",
            "description": (
                "Fuehrt eine PromQL/MetricsQL-Instant-Query gegen VictoriaMetrics aus. "
                "Nutze das nur, wenn eine konkrete Zahl gebraucht wird, die nicht schon "
                "im Systemzustand oben steht."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "PromQL-Ausdruck, z.B. poc:latency_p95:5m{job=\"poc-api\"}"},
                },
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_recent_logs",
            "description": "Holt die juengsten Log-Zeilen eines Service der letzten 10 Minuten aus Loki.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "job-Label, z.B. poc-api oder store-api"},
                    "limit": {"type": "integer", "description": "maximale Anzahl Zeilen, Standard 10"},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_recent_traces",
            "description": "Sucht in Tempo nach den langsamsten Traces eines Service der letzten 15 Minuten.",
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service-Name aus der Topologie, z.B. payment-provider-psp"},
                },
                "required": ["service"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_datasources",
            "description": "Listet die in Grafana konfigurierten Datenquellen (Name, UID, Typ) auf.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_or_update_dashboard",
            "description": (
                "Erstellt ein neues Grafana-Dashboard oder aktualisiert ein bestehendes mit "
                "gleichem Titel. Jedes Panel zeigt eine PromQL/MetricsQL-Zeitreihe aus "
                "VictoriaMetrics. Nutze das, wenn der Nutzer explizit ein Dashboard oder "
                "eine Visualisierung angelegt haben moechte. Erfinde KEINE Metriknamen - "
                "nutze ausschliesslich diese bekannten Recording-Rules (job ist \"poc-api\" "
                "oder \"store-api\"): poc:requests:rate5m, poc:error_ratio:5m, "
                "poc:latency_p95:5m, poc:requests:seasonal_ratio, "
                "poc:business_txn:seasonal_ratio, poc:learning:profile_days. Fuer alles "
                "andere zuerst query_promql zum Testen nutzen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titel des Dashboards"},
                    "panels": {
                        "type": "array",
                        "description": "Ein bis sechs Panels fuer das Dashboard",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Panel-Titel"},
                                "expr": {
                                    "type": "string",
                                    "description": (
                                        "PromQL/MetricsQL-Ausdruck mit einem der bekannten "
                                        "Metriknamen, z.B. poc:latency_p95:5m{job=\"poc-api\"}"
                                    ),
                                },
                                "unit": {
                                    "type": "string",
                                    "description": "Grafana-Einheit, z.B. 'ms', 'percent', 'reqps'. Optional, Standard 'short'.",
                                },
                                "panel_type": {
                                    "type": "string",
                                    "enum": ["timeseries", "stat"],
                                    "description": "Panel-Typ. Optional, Standard 'timeseries'.",
                                },
                            },
                            "required": ["title", "expr"],
                        },
                    },
                },
                "required": ["title", "panels"],
            },
        },
    },
]


async def query_promql(expr: str, **_) -> str:
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{VM_URL}/api/v1/query", params={"query": expr}, timeout=10)
            r.raise_for_status()
            result = r.json()["data"]["result"]
        if not result:
            return "Keine Daten fuer diese Abfrage."
        return "\n".join(
            f"{item['metric']} = {item['value'][1]}" for item in result[:15]
        )
    except Exception as exc:
        return f"Abfrage fehlgeschlagen: {exc}"


async def query_recent_logs(service: str, limit: int = 10, **_) -> str:
    try:
        import time

        limit = int(limit) if limit else 10
        now_ns = int(time.time() * 1e9)
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={
                    "query": f'{{job="{service}"}}',
                    "limit": limit,
                    "start": now_ns - 10 * 60 * 1_000_000_000,
                    "end": now_ns,
                    "direction": "backward",
                },
                timeout=10,
            )
            r.raise_for_status()
            streams = r.json()["data"]["result"]
        lines = []
        for s in streams:
            for ts, line in s["values"]:
                lines.append(line)
        if not lines:
            return f"Keine Log-Zeilen fuer {service} in den letzten 10 Minuten."
        return "\n".join(lines[:limit])
    except Exception as exc:
        return f"Log-Abfrage fehlgeschlagen: {exc}"


async def query_recent_traces(service: str, **_) -> str:
    try:
        traceql = f'{{resource.service.name="{service}" && duration>500ms}}'
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{TEMPO_URL}/api/search",
                params={"q": traceql, "limit": 5},
                timeout=10,
            )
            r.raise_for_status()
            traces = r.json().get("traces", [])
        if not traces:
            return f"Keine Traces fuer {service} gefunden."
        out = []
        for t in traces[:5]:
            dur_ms = t.get("durationMs", "?")
            out.append(f"Trace {t.get('traceID', '?')}: {dur_ms} ms, root={t.get('rootServiceName', '?')}")
        return "\n".join(out)
    except Exception as exc:
        return f"Trace-Suche fehlgeschlagen: {exc}"


async def list_datasources(**_) -> str:
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{GRAFANA_URL}/api/datasources", timeout=10)
            r.raise_for_status()
            data = r.json()
        if not data:
            return "Keine Datenquellen konfiguriert."
        return "\n".join(f"{d['name']} (uid={d['uid']}, typ={d['type']})" for d in data)
    except Exception as exc:
        return f"Datenquellen-Abfrage fehlgeschlagen: {exc}"


async def _find_dashboard_uid(client: httpx.AsyncClient, title: str) -> str | None:
    r = await client.get(
        f"{GRAFANA_URL}/api/search", params={"query": title, "type": "dash-db"}, timeout=10
    )
    r.raise_for_status()
    for item in r.json():
        if item.get("title") == title:
            return item.get("uid")
    return None


def _build_panel(index: int, spec: dict) -> dict | None:
    title = spec.get("title")
    expr = spec.get("expr")
    if not title or not expr:
        return None
    panel_type = spec.get("panel_type") if spec.get("panel_type") in ("timeseries", "stat") else "timeseries"
    unit = spec.get("unit") or "short"
    datasource_ref = {"type": "prometheus", "uid": "victoriametrics"}
    return {
        "id": index + 1,
        "type": panel_type,
        "title": title,
        "gridPos": {"h": 8, "w": 12, "x": (index % 2) * 12, "y": (index // 2) * 8},
        "datasource": datasource_ref,
        "targets": [{"expr": expr, "refId": "A", "datasource": datasource_ref}],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
    }


async def create_or_update_dashboard(title: str, panels: list[dict] | None = None, **_) -> str:
    if not title:
        return "Fehler: Titel fehlt."
    grafana_panels = [p for p in (_build_panel(i, spec) for i, spec in enumerate(panels or [])) if p]
    if not grafana_panels:
        return "Fehler: mindestens ein gueltiges Panel mit 'title' und 'expr' wird benoetigt."

    try:
        async with httpx.AsyncClient() as client:
            existing_uid = await _find_dashboard_uid(client, title)
            dashboard = {
                "id": None,
                "uid": existing_uid,
                "title": title,
                "panels": grafana_panels,
                "schemaVersion": 39,
                "time": {"from": "now-6h", "to": "now"},
                "refresh": "30s",
            }
            r = await client.post(
                f"{GRAFANA_URL}/api/dashboards/db",
                json={"dashboard": dashboard, "overwrite": True},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        verb = "aktualisiert" if existing_uid else "erstellt"
        return f"Dashboard '{title}' {verb}: {GRAFANA_PUBLIC_URL}{data.get('url', '')}"
    except Exception as exc:
        return f"Dashboard-Erstellung fehlgeschlagen: {exc}"


DISPATCH = {
    "query_promql": query_promql,
    "query_recent_logs": query_recent_logs,
    "query_recent_traces": query_recent_traces,
    "list_datasources": list_datasources,
    "create_or_update_dashboard": create_or_update_dashboard,
}


async def run_tool(name: str, arguments: dict) -> str:
    fn = DISPATCH.get(name)
    if fn is None:
        return f"Unbekanntes Tool: {name}"
    try:
        return await fn(**arguments)
    except TypeError as exc:
        return f"Falsche Argumente fuer {name}: {exc}"
