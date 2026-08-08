"""store-api - Backend des stationaeren Filialbetriebs.

Zweiter Einstiegspunkt neben der poc-api. Beim Click & Collect ruft die Filiale
den Onlineshop per HTTP auf - dieser Aufruf ist echt, nicht simuliert, und
erzeugt damit einen Trace, der beide Anwendungen durchspannt.
"""

from __future__ import annotations

import logging
import os
import random

import requests
from fastapi import FastAPI, HTTPException, Response
from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.trace import Status, StatusCode

import store_topology
from simulation import DownstreamError
from store_topology import SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("store-api")

SHOP_URL = os.getenv("SHOP_URL", "http://poc-api:8000")

meter = metrics.get_meter("store-api")

pos_transactions = meter.create_counter(
    "pos.transactions", description="Abgeschlossene Kassenvorgaenge"
)
pos_failed = meter.create_counter(
    "pos.failed", description="Abgebrochene Kassenvorgaenge"
)
pos_revenue = meter.create_counter("pos.revenue", description="Filialumsatz in EUR")
basket_value = meter.create_histogram(
    "pos.basket_value", description="Bonwert an der Kasse in EUR"
)
pallets_moved = meter.create_counter(
    "warehouse.pallets", description="Im Lager bewegte Paletten"
)
dependency_duration = meter.create_histogram(
    "dependency.duration",
    unit="ms",
    description="Antwortzeit der aufgerufenen Downstream-Services",
)


def _record_dependency(service: str, millis: float) -> None:
    dependency_duration.record(millis, {"dependency": service})


def _chaos_gauge(options: CallbackOptions):
    active = store_topology.chaos.active
    for name, cfg in SCENARIOS.items():
        yield Observation(
            1 if name == active else 0, {"scenario": name, "label": cfg["label"]}
        )


meter.create_observable_gauge(
    "chaos.scenario.active",
    callbacks=[_chaos_gauge],
    description="Aktives Stoerungsszenario der Filiale",
)

# Zaehler einmal mit 0 anlegen: sonst existiert die Zeitreihe ausserhalb der
# Oeffnungszeiten gar nicht und die Dashboard-Panels bleiben leer.
for _counter in (pos_transactions, pos_failed, pos_revenue, pallets_moved):
    _counter.add(0)

app = FastAPI(title="store-api", version="1.0.0")


def _journey(name: str, response: Response, payload: dict | None = None):
    span = trace.get_current_span()
    span.set_attribute("store.process", name)
    try:
        store_topology.run_journey(name, _record_dependency)
    except DownstreamError as exc:
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        logger.error("Filialprozess '%s' abgebrochen: %s", name, exc)
        response.status_code = 500
        return {"status": "error", "process": name, "failed_service": exc.service}
    return {"status": "ok", "process": name, **(payload or {})}


@app.get("/health")
def health():
    return {
        "status": "up",
        "scenario": store_topology.chaos.active,
        "services": store_topology.service_count(),
    }


@app.post("/store/checkout")
def pos_checkout(response: Response):
    """Kassenvorgang: Preis, Kartenzahlung, Fiskalbon, Bonuspunkte, Bestandsabgang."""
    basket = round(random.uniform(4.9, 189.0), 2)
    span = trace.get_current_span()
    span.set_attribute("pos.basket_value_eur", basket)
    span.set_attribute("pos.items", random.randint(1, 14))

    result = _journey("pos-checkout", response, {"basket_value_eur": basket})
    if result["status"] == "error":
        pos_failed.add(1, {"reason": result["failed_service"]})
        return result

    basket_value.record(basket)
    pos_transactions.add(1)
    pos_revenue.add(basket)
    return result


@app.post("/store/click-collect")
def click_collect(response: Response):
    """Holt die Bestelldaten beim Onlineshop und kommissioniert sie in der Filiale."""
    span = trace.get_current_span()
    try:
        # Echter HTTP-Aufruf: die Instrumentierung propagiert den traceparent,
        # der Trace laeuft damit ueber beide Anwendungen hinweg.
        resp = requests.get(f"{SHOP_URL}/api/orders", timeout=30)
        span.set_attribute("shop.status_code", resp.status_code)
        if resp.status_code >= 500:
            span.set_status(Status(StatusCode.ERROR, "Onlineshop nicht erreichbar"))
            logger.error("Click & Collect: Onlineshop antwortet mit %s", resp.status_code)
            response.status_code = 502
            return {"status": "error", "process": "click-collect", "failed_service": "poc-api"}
    except requests.RequestException as exc:
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        logger.error("Click & Collect: Onlineshop nicht erreichbar (%s)", exc)
        response.status_code = 502
        return {"status": "error", "process": "click-collect", "failed_service": "poc-api"}

    return _journey("click-collect", response)


@app.post("/store/returns")
def returns(response: Response):
    return _journey("returns", response)


@app.get("/store/price-check")
def price_check(response: Response):
    return _journey("price-check", response)


@app.post("/store/goods-receipt")
def goods_receipt(response: Response):
    result = _journey("goods-receipt", response)
    if result["status"] == "ok":
        pallets_moved.add(random.randint(1, 6))
    return result


@app.post("/store/shelf-labels")
def shelf_labels(response: Response):
    return _journey("shelf-labels", response)


@app.post("/store/staff-planning")
def staff_planning(response: Response):
    return _journey("staff-planning", response)


@app.get("/store/facility")
def facility(response: Response):
    return _journey("facility", response)


@app.post("/store/replenishment")
def replenishment(response: Response):
    result = _journey("replenishment", response)
    if result["status"] == "ok":
        pallets_moved.add(random.randint(4, 20))
    return result


@app.post("/store/stocktaking")
def stocktaking(response: Response):
    return _journey("stocktaking", response)


# --- Steuerung der Demo ------------------------------------------------------
@app.get("/chaos")
def chaos_status():
    active = store_topology.chaos.active
    return {
        "active": active,
        "detail": SCENARIOS[active],
        "available": {k: v["label"] for k, v in SCENARIOS.items()},
    }


@app.post("/chaos/{scenario}")
def set_chaos(scenario: str):
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"unbekanntes Szenario: {scenario} (verfügbar: {', '.join(SCENARIOS)})",
        )
    detail = store_topology.chaos.set(scenario)
    logger.warning("Filial-Szenario umgeschaltet auf '%s' (%s)", scenario, detail["label"])
    return {"active": scenario, "detail": detail}
