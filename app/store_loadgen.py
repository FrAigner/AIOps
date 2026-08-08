"""Lastgenerator für den Filialbetrieb - mit Öffnungszeiten statt 24/7.

Der stationäre Handel hat einen völlig anderen Rhythmus als der Onlineshop:
nachts läuft nur Logistik und Nachschub, morgens der Wareneingang, tagsüber die
Kasse mit Mittags- und Feierabendspitze, sonntags ist geschlossen. Genau dieser
Kontrast macht im Dashboard sichtbar, dass die Anomalieerkennung den normalen
Tagesrhythmus nicht mit einer Störung verwechseln darf.
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

TARGET = os.getenv("TARGET_URL", "http://store-api:8001")
PEAK_RPS = float(os.getenv("LOADGEN_PEAK_RPS", "4.0"))
MAX_INFLIGHT = int(os.getenv("LOADGEN_MAX_INFLIGHT", "16"))
DAY_SECONDS = float(os.getenv("LOADGEN_DAY_SECONDS", str(24 * 3600)))

OPENING_HOUR = int(os.getenv("STORE_OPENING_HOUR", "7"))
CLOSING_HOUR = int(os.getenv("STORE_CLOSING_HOUR", "20"))

# Kundenfrequenz je Öffnungsstunde, 1.0 = Mittagsspitze.
CUSTOMER_SHAPE = {
    7: 0.25, 8: 0.45, 9: 0.62, 10: 0.78, 11: 0.95, 12: 1.00,
    13: 0.88, 14: 0.72, 15: 0.74, 16: 0.86, 17: 0.98, 18: 0.95,
    19: 0.70,
}

# (Methode, Pfad, Gewicht) je Betriebsphase
PHASES: dict[str, list[tuple[str, str, int]]] = {
    "night": [                       # 00-06: Nachschub, Disposition, Inventur
        ("POST", "/store/replenishment", 40),
        ("POST", "/store/stocktaking", 25),
        ("GET", "/store/facility", 20),
        ("POST", "/store/shelf-labels", 15),
    ],
    "opening": [                     # 06-07: Wareneingang und Vorbereitung
        ("POST", "/store/goods-receipt", 45),
        ("POST", "/store/shelf-labels", 25),
        ("POST", "/store/staff-planning", 15),
        ("GET", "/store/facility", 15),
    ],
    "trading": [                     # Öffnungszeiten
        ("POST", "/store/checkout", 46),
        ("GET", "/store/price-check", 20),
        ("POST", "/store/click-collect", 13),
        ("POST", "/store/returns", 8),
        ("POST", "/store/goods-receipt", 6),
        ("POST", "/store/shelf-labels", 4),
        ("GET", "/store/facility", 3),
    ],
    "closing": [                     # 20-22: Kassenabschluss, Inventur
        ("POST", "/store/stocktaking", 40),
        ("POST", "/store/staff-planning", 25),
        ("POST", "/store/shelf-labels", 20),
        ("GET", "/store/facility", 15),
    ],
    "sunday": [                      # geschlossen: nur Gebäudetechnik und Lager
        ("GET", "/store/facility", 55),
        ("POST", "/store/replenishment", 30),
        ("POST", "/store/stocktaking", 15),
    ],
}


def virtual_now() -> datetime:
    if DAY_SECONDS >= 24 * 3600:
        return datetime.now()
    frac = (time.time() % DAY_SECONDS) / DAY_SECONDS
    minutes = int(frac * 24 * 60)
    return datetime.now().replace(
        hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0
    )


def phase_of(now: datetime) -> str:
    if now.weekday() == 6:  # Sonntag: Ladenschluss
        return "sunday"
    if now.hour < OPENING_HOUR - 1:
        return "night"
    if now.hour < OPENING_HOUR:
        return "opening"
    if now.hour < CLOSING_HOUR:
        return "trading"
    if now.hour < 22:
        return "closing"
    return "night"


def load_factor(now: datetime) -> float:
    phase = phase_of(now)
    if phase == "trading":
        cur = CUSTOMER_SHAPE.get(now.hour, 0.5)
        nxt = CUSTOMER_SHAPE.get((now.hour + 1) % 24, cur)
        base = cur * (1 - now.minute / 60) + nxt * (now.minute / 60)
        if now.weekday() == 5:  # Samstag ist der stärkste Tag im Handel
            base *= 1.35
        return base * random.uniform(0.9, 1.1)
    # Hintergrundbetrieb läuft konstant, aber deutlich schwächer.
    return {"night": 0.22, "opening": 0.32, "closing": 0.20, "sunday": 0.10}[phase]


def pick_request(now: datetime) -> tuple[str, str]:
    rows = PHASES[phase_of(now)]
    return random.choices(
        [(m, p) for m, p, _ in rows], weights=[w for *_, w in rows], k=1
    )[0]


def fire(method: str, path: str) -> None:
    req = urllib.request.Request(f"{TARGET}{path}", method=method)
    if method == "POST":
        req.data = b"{}"
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        pass


def wait_for_api() -> None:
    for _ in range(90):
        try:
            with urllib.request.urlopen(f"{TARGET}/health", timeout=3) as r:
                info = json.loads(r.read())
            print(
                f"store-loadgen: store-api bereit, {info.get('services')} Services",
                flush=True,
            )
            return
        except OSError:
            time.sleep(2)
    print("store-loadgen: store-api nicht erreichbar, starte trotzdem", flush=True)


def report_loop() -> None:
    while True:
        now = virtual_now()
        print(
            f"store-loadgen: {now:%a %H:%M} – Phase '{phase_of(now)}', "
            f"Lastfaktor {load_factor(now):.2f}",
            flush=True,
        )
        time.sleep(60)


def main() -> None:
    wait_for_api()
    threading.Thread(target=report_loop, daemon=True).start()

    pool = ThreadPoolExecutor(max_workers=MAX_INFLIGHT)
    while True:
        now = virtual_now()
        rps = max(PEAK_RPS * load_factor(now), 0.2)
        method, path = pick_request(now)
        pool.submit(fire, method, path)
        time.sleep(random.expovariate(rps))


if __name__ == "__main__":
    main()
