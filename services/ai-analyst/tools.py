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


DISPATCH = {
    "query_promql": query_promql,
    "query_recent_logs": query_recent_logs,
    "query_recent_traces": query_recent_traces,
}


async def run_tool(name: str, arguments: dict) -> str:
    fn = DISPATCH.get(name)
    if fn is None:
        return f"Unbekanntes Tool: {name}"
    try:
        return await fn(**arguments)
    except TypeError as exc:
        return f"Falsche Argumente fuer {name}: {exc}"
