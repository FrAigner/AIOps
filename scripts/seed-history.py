#!/usr/bin/env python3
"""Fuellt VictoriaMetrics mit Vergleichstagen, damit das saisonale Lernen sofort greift.

Warum es das gibt
-----------------
Das Tagesprofil in ``config/vmalert-rules.yaml`` vergleicht die aktuelle Lage mit
derselben Uhrzeit an den Vortagen und am Vortag der Vorwoche. Frisch gestartet hat
der Stack diese Historie nicht - das Profil braucht bei echtem Betrieb einen Tag,
bis es den ersten Vergleichswert hat, und eine Woche bis zur vollen Genauigkeit.

Fuer eine Vorfuehrung ist das zu lang. Dieses Skript schreibt deshalb einmalig die
Tage VOR dem Start des Stacks nach - danach steht das saisonale Lernen sofort auf
vier Vergleichstagen.

Was hier ehrlich zu sagen ist: diese Werte sind erzeugt, nicht gemessen. Sie sind
kein Beleg fuer irgendetwas. Sie stammen aus demselben Tagesverlauf, den die
Lastgeneratoren auch live erzeugen (``HOURLY_SHAPE`` bzw. ``CUSTOMER_SHAPE``),
skaliert auf das Niveau, das im laufenden Betrieb tatsaechlich gemessen wurde.
Damit sieht das gelernte Profil so aus, wie es nach ein paar Tagen Echtbetrieb
auch aussehen wuerde.

Geschrieben wird ausschliesslich in Zeitraeume VOR dem ersten echten Datenpunkt.
Vorhandene Messwerte werden nicht ueberschrieben und nicht vermischt.

Aufruf
------
    python3 scripts/seed-history.py            # 8 Tage, schreibt
    python3 scripts/seed-history.py --dry-run  # nur anzeigen, was passieren wuerde
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import loadgen  # noqa: E402
import store_loadgen  # noqa: E402

VM = os.getenv("VM_URL", "http://localhost:8428")
STEP = 300  # 5-Minuten-Raster, wie die Recording Rules es liefern

# Latenzprofil ueber den Tag, relativ zum Tagesniveau (1.0).
# Nicht die Last treibt die Latenz, sondern der Traffic-Mix: nachts wird
# gestoebert (billige Endpunkte), tagsueber und abends gekauft (Checkout mit
# Zahlungsstrecke). Gemessen ueber 17 Stunden Normalbetrieb: nachts rund 310 ms,
# mittags rund 530 ms. Die Abendstunden lagen zum Zeitpunkt der Messung noch
# nicht vor und sind aus dem Mix abgeleitet - abends ist der Checkout-Anteil am
# hoechsten, die Latenz also minimal ueber dem Tagesniveau.
LAT_PROFILE = [
    0.62, 0.60, 0.58, 0.58, 0.58, 0.60,   # 00-05
    0.62, 0.72, 0.84, 0.92, 0.98, 1.00,   # 06-11
    1.00, 1.00, 1.00, 1.00, 1.00, 1.01,   # 12-17
    1.02, 1.02, 1.02, 1.00, 0.86, 0.70,   # 18-23
]


def query(expr: str):
    url = f"{VM}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)["data"]["result"]


def query_range(expr: str, start: int, end: int, step: int = 900):
    url = f"{VM}/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": expr, "start": start, "end": end, "step": step}
    )
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)["data"]["result"]


def first_sample(expr: str) -> int | None:
    """Zeitstempel des aeltesten vorhandenen Messwerts."""
    now = int(time.time())
    res = query_range(expr, now - 30 * 86400, now, 900)
    stamps = [v[0] for s in res for v in s["values"]]
    return int(min(stamps)) if stamps else None


def interp(profile, now: datetime) -> float:
    """Weiche Interpolation zwischen zwei Stundenwerten."""
    f = now.minute / 60.0
    return profile[now.hour] * (1 - f) + profile[(now.hour + 1) % 24] * f


def checkout_share(now: datetime) -> float:
    """Anteil der Checkout-Requests am Traffic - aus dem echten Mix des Lastgenerators."""
    col = loadgen._mix_column(now.hour)
    total = sum(row[col] for row in loadgen.TRAFFIC_MIX)
    checkout = next(r[col] for r in loadgen.TRAFFIC_MIX if r[1] == "/api/checkout")
    return checkout / total


# Anteil der Kassenvorgaenge am Filial-Traffic waehrend der Ladenoeffnung -
# aus dem echten Mix des Store-Lastgenerators (nur die "trading"-Phase kennt
# ueberhaupt Kassenvorgaenge, night/opening/closing/sunday sind reiner
# Hintergrundbetrieb ohne Verkauf).
_STORE_TRADING = store_loadgen.PHASES["trading"]
_STORE_CHECKOUT_SHARE = (
    next(r[2] for r in _STORE_TRADING if r[1] == "/store/checkout")
    / sum(r[2] for r in _STORE_TRADING)
)


def store_checkout_share(now: datetime) -> float:
    return _STORE_CHECKOUT_SHARE if store_loadgen.phase_of(now) == "trading" else 0.0


def calibrate(expr: str, shape_fn, start: int, end: int, fallback: float) -> float:
    """Skalierungsfaktor aus dem echten Betrieb ableiten.

    Verhaeltnis Messwert zu Profilwert, ueber alle vorhandenen Samples.
    Median statt Mittelwert, damit einzelne Chaos-Tests in der Historie
    das Ergebnis nicht verziehen.
    """
    res = query_range(expr, start, end, 900)
    ratios = []
    for s in res:
        for ts, val in s["values"]:
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if v != v or v <= 0:
                continue
            shape = shape_fn(datetime.fromtimestamp(ts))
            if shape > 0.01:
                ratios.append(v / shape)
    if not ratios:
        print(f"    (keine Messwerte fuer {expr}, nutze Vorgabe {fallback})")
        return fallback
    return statistics.median(ratios)


def build_series(days: int, cutoff: int, only: str):
    """Erzeugt alle Zeitreihen fuer den Zeitraum vor ``cutoff``."""
    def want(kind: str) -> bool:
        return only in ("all", kind)

    end = cutoff - STEP
    start = cutoff - days * 86400
    lookback_start, lookback_end = cutoff, int(time.time())

    print("[1] Kalibrierung am laufenden Betrieb")
    shop_scale = calibrate(
        'poc:requests:rate5m{job="poc-api"}',
        lambda d: loadgen.HOURLY_SHAPE[d.hour],
        lookback_start, lookback_end, 6.0,
    )
    store_scale = calibrate(
        'poc:requests:rate5m{job="store-api"}',
        lambda d: max(store_loadgen.load_factor(d), 0.05),
        lookback_start, lookback_end, 3.0,
    )
    lat_shop = calibrate(
        'poc:latency_p95:5m{job="poc-api"}',
        lambda d: LAT_PROFILE[d.hour],
        lookback_start, lookback_end, 530.0,
    )
    lat_store = calibrate(
        'poc:latency_p95:5m{job="store-api"}',
        lambda d: LAT_PROFILE[d.hour],
        lookback_start, lookback_end, 400.0,
    )
    # Bestellungen bewusst am Ist kalibriert und nicht aus dem Traffic-Mix
    # hochgerechnet: nicht jeder Checkout-Request wird zu einer Bestellung
    # (abgebrochene Warenkoerbe, Fehlschlaege). Aus dem Mix gerechnet lag die
    # Erwartung um Faktor 1,8 zu hoch - der Detektor haette den Normalbetrieb
    # bereits als Einbruch gemeldet.
    orders_scale = calibrate(
        'poc:orders:rate5m{job="poc-api"}',
        lambda d: loadgen.HOURLY_SHAPE[d.hour] * checkout_share(d),
        lookback_start, lookback_end, 0.5,
    )
    # Dieselbe Kalibrierung fuer die Filiale, auf poc:business_txn:rate5m -
    # das ist die Reihe, gegen die POSVolumeAnomaly tatsaechlich prueft.
    pos_scale = calibrate(
        'poc:business_txn:rate5m{job="store-api"}',
        lambda d: store_loadgen.load_factor(d) * store_checkout_share(d),
        lookback_start, lookback_end, 0.4,
    )
    print(f"    Shop-Traffic   : {shop_scale:6.2f} req/s bei Tagesniveau 1.0")
    print(f"    Filial-Traffic : {store_scale:6.2f} req/s bei Tagesniveau 1.0")
    print(f"    Shop-P95       : {lat_shop:6.1f} ms")
    print(f"    Filial-P95     : {lat_store:6.1f} ms")
    print(f"    Bestellungen   : {orders_scale:6.2f} /s bei Tagesniveau 1.0")
    print(f"    Kassenvorgaenge: {pos_scale:6.2f} /s bei Tagesniveau 1.0 (nur Oeffnungszeit)")

    series: dict[tuple[str, str], list[tuple[int, float]]] = {}

    def add(name: str, job: str, ts: int, val: float) -> None:
        series.setdefault((name, job), []).append((ts, max(val, 0.0)))

    ts = start
    while ts <= end:
        d = datetime.fromtimestamp(ts)

        shop_rps = shop_scale * loadgen.load_factor(d)
        if want("requests"):
            add("poc:requests:rate5m", "poc-api", ts, shop_rps)
        if want("latency"):
            add("poc:latency_p95:5m", "poc-api", ts,
                lat_shop * interp(LAT_PROFILE, d) * random.uniform(0.92, 1.08))
        # Bestellungen folgen dem Tagesverlauf mal dem Checkout-Anteil des
        # Mixes - der Absolutwert kommt aus der Kalibrierung, nicht aus der
        # Rechnung.
        if want("orders"):
            shop_orders = orders_scale * loadgen.load_factor(d) * checkout_share(d) \
                * random.uniform(0.85, 1.15)
            add("poc:orders:rate5m", "poc-api", ts, shop_orders)
            add("poc:business_txn:rate5m", "poc-api", ts, shop_orders)

        store_rps = max(store_scale * store_loadgen.load_factor(d), 0.05)
        if want("requests"):
            add("poc:requests:rate5m", "store-api", ts, store_rps)
        if want("latency"):
            add("poc:latency_p95:5m", "store-api", ts,
                lat_store * interp(LAT_PROFILE, d) * random.uniform(0.92, 1.08))
        if want("orders"):
            store_share = store_checkout_share(d)
            pos_rate = (pos_scale * store_loadgen.load_factor(d) * store_share
                        * random.uniform(0.85, 1.15)) if store_share > 0 else 0.0
            add("poc:business_txn:rate5m", "store-api", ts, pos_rate)

        ts += STEP

    return series, start, end


def push(series, dry_run: bool) -> int:
    lines = []
    for (name, job), points in series.items():
        lines.append(json.dumps({
            "metric": {"__name__": name, "job": job},
            "values": [round(v, 4) for _, v in points],
            "timestamps": [t * 1000 for t, _ in points],
        }))
    payload = ("\n".join(lines) + "\n").encode()
    if dry_run:
        return sum(len(p) for p in series.values())
    req = urllib.request.Request(
        f"{VM}/api/v1/import", data=payload,
        headers={"Content-Type": "application/x-ndjson"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        if r.status not in (200, 204):
            raise SystemExit(f"Import fehlgeschlagen: HTTP {r.status}")
    return sum(len(p) for p in series.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8,
                    help="Anzahl nachzutragender Tage (Vorgabe 8, deckt auch den 7d-Lag ab)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["all", "requests", "latency", "orders"], default="all",
                    help="nur eine Kennzahl nachtragen - fuer Nachbesserungen, ohne die "
                         "uebrigen Reihen doppelt zu schreiben")
    args = ap.parse_args()

    random.seed(20260806)  # reproduzierbar

    # Grenze immer an der Reihe bestimmen, die tatsaechlich beschrieben wird.
    # Sonst zeigt ein zweiter Lauf auf den Beginn der bereits nachgetragenen
    # Historie und schreibt weitere acht Tage davor - also am Zeitfenster
    # vorbei, das die Lags ueberhaupt abfragen.
    target = {
        "all": 'poc:requests:rate5m{job="poc-api"}',
        "requests": 'poc:requests:rate5m{job="poc-api"}',
        "latency": 'poc:latency_p95:5m{job="poc-api"}',
        "orders": 'poc:orders:rate5m{job="poc-api"}',
    }[args.only]
    cutoff = first_sample(target)
    if cutoff is None:
        raise SystemExit(
            "Keine Messdaten gefunden. Erst den Stack ein paar Minuten laufen lassen -\n"
            "das Skript kalibriert die Historie am echten Betrieb."
        )
    print(f"    Erster echter Messwert: {datetime.fromtimestamp(cutoff)}")
    print("    Es wird ausschliesslich davor geschrieben.\n")

    series, start, end = build_series(args.days, cutoff, args.only)

    print("\n[2] Schreiben")
    n = push(series, args.dry_run)
    print(f"    Zeitraum : {datetime.fromtimestamp(start)}  bis  {datetime.fromtimestamp(end)}")
    print(f"    Reihen   : {len(series)}")
    print(f"    Punkte   : {n}")
    print("    (Testlauf, nichts geschrieben)" if args.dry_run else "    geschrieben.")

    if not args.dry_run:
        print("\n[3] Das Tagesprofil steht nach der naechsten Auswertung (30s) zur Verfuegung:")
        print("    poc:learning:profile_days   -> Anzahl gelernter Vergleichstage")
        print("    poc:requests:seasonal       -> erwarteter Traffic zu dieser Uhrzeit")


if __name__ == "__main__":
    main()
