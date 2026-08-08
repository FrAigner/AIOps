"""HTTP-Zugriff auf VictoriaMetrics - dasselbe urllib-Muster wie
scripts/seed-history.py, bewusst ohne zusaetzliche HTTP-Client-Abhaengigkeit.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

import pandas as pd

VM = os.getenv("VM_URL", "http://victoriametrics:8428")


def query_range(expr: str, start: int, end: int, step: int = 900) -> list[dict]:
    url = f"{VM}/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": expr, "start": start, "end": end, "step": step}
    )
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)["data"]["result"]


def fetch_series(expr: str, job: str, days: int) -> pd.Series:
    now = int(time.time())
    start = now - days * 86400
    res = query_range(f'{expr}{{job="{job}"}}', start, now, step=900)
    if not res:
        return pd.Series(dtype=float)
    values = res[0]["values"]
    idx = pd.to_datetime([v[0] for v in values], unit="s")
    s = pd.Series([float(v[1]) for v in values], index=idx).sort_index()
    # 15-Minuten-Raster erzwingen, kleine Luecken (bis 1h) interpolieren,
    # groessere Luecken NICHT erzwingen - lieber ehrlich fehlende Historie
    # als erfundene Werte.
    return s.asfreq("15min").interpolate(limit=4)


def push(metrics: dict[str, dict], timestamp_ms: int) -> None:
    """metrics: {metric_name: {"job": job, "value": float}}"""
    lines = []
    for name, spec in metrics.items():
        lines.append(json.dumps({
            "metric": {"__name__": name, "job": spec["job"]},
            "values": [round(float(spec["value"]), 4)],
            "timestamps": [timestamp_ms],
        }))
    payload = ("\n".join(lines) + "\n").encode()
    req = urllib.request.Request(
        f"{VM}/api/v1/import", data=payload,
        headers={"Content-Type": "application/x-ndjson"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status not in (200, 204):
            raise RuntimeError(f"VM-Import fehlgeschlagen: HTTP {r.status}")
