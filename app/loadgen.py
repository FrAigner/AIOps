"""Lastgenerator mit Tagesverlauf.

Bildet den typischen Rhythmus eines Onlineshops ab: nachts fast still, Vormittag
ansteigend, Mittagsspitze, kräftiger Abendpeak, Wochenende stärker als Werktage.
Auch der Traffic-Mix verschiebt sich - nachts wird gestöbert, abends gekauft.

Laeuft bewusst ohne OTel-Instrumentierung, damit die Traces in Tempo sauber mit
dem Server-Span der poc-api als Root beginnen.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

TARGET = os.getenv("TARGET_URL", "http://poc-api:8000")
PEAK_RPS = float(os.getenv("LOADGEN_PEAK_RPS", "6.0"))
MAX_INFLIGHT = int(os.getenv("LOADGEN_MAX_INFLIGHT", "24"))

# Länge eines simulierten Tages in Sekunden. Standard: echte Uhrzeit.
# Für eine Vorführung lässt sich der Tagesverlauf zusammenstauchen, z. B.
# LOADGEN_DAY_SECONDS=1800 zeigt 24 Stunden in einer halben Stunde.
DAY_SECONDS = float(os.getenv("LOADGEN_DAY_SECONDS", str(24 * 3600)))

# Relative Last je Stunde (0-23), 1.0 = Mittagsniveau.
HOURLY_SHAPE = [
    0.22, 0.15, 0.11, 0.09, 0.10, 0.16,   # 00-05 Nacht
    0.30, 0.52, 0.70, 0.80, 0.86, 0.94,   # 06-11 Vormittag
    1.00, 0.93, 0.86, 0.84, 0.90, 1.06,   # 12-17 Mittag & Nachmittag
    1.24, 1.32, 1.18, 0.88, 0.58, 0.34,   # 18-23 Abendpeak
]

# Traffic-Mix nach Tageszeit: (Pfad, Methode, Gewicht nachts, Gewicht tagsüber, Gewicht abends)
TRAFFIC_MIX = [
    ("GET", "/api/home", 30, 26, 22),
    ("GET", "/api/search", 26, 24, 20),
    ("GET", "/api/products", 28, 26, 24),
    ("POST", "/api/cart", 9, 13, 17),
    ("POST", "/api/checkout", 4, 8, 14),
    ("GET", "/api/orders", 3, 3, 3),
]


def virtual_now() -> datetime:
    """Uhrzeit im simulierten Tag - bei Standardeinstellung die echte Ortszeit."""
    if DAY_SECONDS >= 24 * 3600:
        return datetime.now()
    frac = (time.time() % DAY_SECONDS) / DAY_SECONDS
    total_minutes = int(frac * 24 * 60)
    return datetime.now().replace(
        hour=total_minutes // 60, minute=total_minutes % 60, second=0, microsecond=0
    )


def load_factor(now: datetime) -> float:
    """Sanft interpolierter Tagesverlauf inklusive Wochenend-Aufschlag."""
    hour, nxt = now.hour, (now.hour + 1) % 24
    frac = now.minute / 60.0
    base = HOURLY_SHAPE[hour] * (1 - frac) + HOURLY_SHAPE[nxt] * frac
    weekend = 1.2 if now.weekday() >= 5 else 1.0
    jitter = random.uniform(0.9, 1.1)
    return base * weekend * jitter


def _mix_column(hour: int) -> int:
    if hour < 7 or hour >= 22:
        return 2  # nachts: stöbern
    if hour >= 17:
        return 4  # abends: kaufen
    return 3


def pick_request(now: datetime) -> tuple[str, str]:
    col = _mix_column(now.hour)
    entries = [(m, p) for m, p, *_ in TRAFFIC_MIX]
    weights = [row[col] for row in TRAFFIC_MIX]
    return random.choices(entries, weights=weights, k=1)[0]


def fire(method: str, path: str) -> None:
    req = urllib.request.Request(f"{TARGET}{path}", method=method)
    if method == "POST":
        req.data = b"{}"
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        pass  # 5xx sind erwünscht - sie sind Teil der Demo


def wait_for_api() -> None:
    for _ in range(90):
        try:
            with urllib.request.urlopen(f"{TARGET}/health", timeout=3) as r:
                info = json.loads(r.read())
            print(
                f"loadgen: poc-api bereit, {info.get('services')} Services in der Topologie",
                flush=True,
            )
            return
        except OSError:
            time.sleep(2)
    print("loadgen: poc-api nicht erreichbar, starte trotzdem", flush=True)


def report_loop() -> None:
    while True:
        now = virtual_now()
        print(
            f"loadgen: {now:%a %H:%M} – Lastfaktor {load_factor(now):.2f} "
            f"(~{PEAK_RPS * load_factor(now):.1f} req/s)",
            flush=True,
        )
        time.sleep(60)


def main() -> None:
    wait_for_api()
    if DAY_SECONDS < 24 * 3600:
        print(f"loadgen: Zeitraffer aktiv – ein Tag dauert {DAY_SECONDS:.0f}s", flush=True)
    threading.Thread(target=report_loop, daemon=True).start()

    pool = ThreadPoolExecutor(max_workers=MAX_INFLIGHT)
    while True:
        now = virtual_now()
        rps = max(PEAK_RPS * load_factor(now), 0.3)
        method, path = pick_request(now)
        pool.submit(fire, method, path)
        # Poisson-artige Abstände wirken realistischer als ein fixer Takt.
        time.sleep(random.expovariate(rps))


if __name__ == "__main__":
    main()
