"""Periodischer Loop: zieht Historie aus VictoriaMetrics, dekomponiert sie
per MSTL (siehe forecast.py) und schreibt Erwartungswert + Konfidenzband
zurueck. Laeuft dauerhaft, analog zu app/loadgen.py.
"""

from __future__ import annotations

import logging
import os
import time

import vm_client
from forecast import decompose_and_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s ml-anomaly %(message)s")
log = logging.getLogger("ml-anomaly")

METRICS = ["poc:requests:rate5m", "poc:latency_p95:5m", "poc:business_txn:rate5m"]
JOBS = ["poc-api", "store-api"]

## VictoriaMetrics/Prometheus-Instant-Queries haben ein Staleness-Fenster von
# standardmaessig 5 Minuten: ein Wert, der laenger nicht neu geschrieben wurde,
# gilt als "kein Datenpunkt". Bei 900s Intervall waeren die ml:*-Reihen also
# 10 von 15 Minuten fuer vmalert unsichtbar und die MLAnomalyDetected-Alarme
# koennten nicht zuverlaessig auswerten. Deshalb deutlich unter 5 Minuten,
# obwohl sich die MSTL-Dekomposition selbst kaum lohnt, so oft neu zu fitten
# (Fit-Dauer fuer alle 6 Reihen zusammen liegt im Test bei ~1-2 Sekunden).
INTERVAL = int(os.getenv("ML_INTERVAL_SECONDS", "120"))
LOOKBACK_DAYS = int(os.getenv("ML_LOOKBACK_DAYS", "21"))


def process_series(metric: str, job: str) -> None:
    series = vm_client.fetch_series(metric, job, days=LOOKBACK_DAYS)
    result = decompose_and_score(series)

    base = metric.removeprefix("poc:")
    now_ms = int(time.time() * 1000)

    if result is None:
        log.info("zu wenig Historie fuer %s{job=%s} (%d Punkte) - kein Schreibvorgang",
                  metric, job, len(series.dropna()))
        vm_client.push({"ml:model:cycles": {"job": job, "value": 0}}, now_ms)
        return

    vm_client.push({
        f"ml:{base}:forecast": {"job": job, "value": result.forecast},
        f"ml:{base}:upper": {"job": job, "value": result.upper},
        f"ml:{base}:lower": {"job": job, "value": result.lower},
        "ml:model:cycles": {"job": job, "value": result.cycles},
    }, now_ms)
    log.info("%s{job=%s}: Erwartung=%.2f Band=[%.2f, %.2f] Zyklen=%d",
              metric, job, result.forecast, result.lower, result.upper, result.cycles)


def main() -> None:
    log.info("Start - Intervall=%ss, Lookback=%sd", INTERVAL, LOOKBACK_DAYS)
    while True:
        start = time.time()
        for job in JOBS:
            for metric in METRICS:
                try:
                    process_series(metric, job)
                except Exception:
                    log.exception("Zyklus fehlgeschlagen fuer %s{job=%s}", metric, job)
        elapsed = time.time() - start
        time.sleep(max(INTERVAL - elapsed, 5))


if __name__ == "__main__":
    main()
