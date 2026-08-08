"""poc-api - Storefront/Gateway eines simulierten Onlineshops.

Der Service ist der einzige echte HTTP-Einstiegspunkt. Die dahinterliegende
Microservice-Landschaft wird in topology.py als eigenständige Services mit
eigener service.name-Resource emuliert - Tempo leitet daraus die
Service-Landkarte ab.
"""

from __future__ import annotations

import logging
import random
import time

from fastapi import FastAPI, HTTPException, Response
from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.trace import Status, StatusCode

import topology
from simulation import DownstreamError
from topology import SCENARIOS

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("poc-api")

meter = metrics.get_meter("poc-api")

# --- Business-Metriken -------------------------------------------------------
orders_created = meter.create_counter(
    "orders.created", description="Erfolgreich abgeschlossene Bestellungen"
)
orders_failed = meter.create_counter(
    "orders.failed", description="Abgebrochene Bestellungen"
)
order_revenue = meter.create_counter("orders.revenue", description="Umsatz in EUR")
cart_value = meter.create_histogram(
    "checkout.cart_value", description="Warenkorbwert in EUR"
)
dependency_duration = meter.create_histogram(
    "dependency.duration",
    unit="ms",
    description="Antwortzeit der aufgerufenen Downstream-Services",
)


def _record_dependency(service: str, millis: float) -> None:
    dependency_duration.record(millis, {"dependency": service})


def _chaos_gauge(options: CallbackOptions):
    """Exportiert das aktive Szenario als Gauge (1 = aktiv) inkl. Klartext-Label."""
    active = topology.chaos.active
    for name, cfg in SCENARIOS.items():
        yield Observation(
            1 if name == active else 0, {"scenario": name, "label": cfg["label"]}
        )


meter.create_observable_gauge(
    "chaos.scenario.active",
    callbacks=[_chaos_gauge],
    description="Aktives Stoerungsszenario der Demo",
)

# Zaehler einmal mit 0 anlegen, damit die Business-Panels von Anfang an
# eine Zeitreihe haben.
for _counter in (orders_created, orders_failed, order_revenue):
    _counter.add(0)

app = FastAPI(title="poc-api", version="3.0.0")


def _journey(name: str, response: Response, payload: dict | None = None):
    """Führt eine User Journey durch die Shop-Landschaft aus."""
    span = trace.get_current_span()
    span.set_attribute("shop.journey", name)
    try:
        topology.run_journey(name, _record_dependency)
    except DownstreamError as exc:
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        logger.error("Journey '%s' abgebrochen: %s", name, exc)
        response.status_code = 500
        return {"status": "error", "journey": name, "failed_service": exc.service}
    return {"status": "ok", "journey": name, **(payload or {})}


@app.get("/health")
def health():
    return {
        "status": "up",
        "scenario": topology.chaos.active,
        "services": topology.service_count(),
    }


@app.get("/api/home")
def home(response: Response):
    return _journey("home", response)


@app.get("/api/search")
def search(response: Response):
    return _journey("search", response)


@app.get("/api/products")
def product_detail(response: Response):
    return _journey("product", response)


@app.post("/api/cart")
def add_to_cart(response: Response):
    return _journey("cart", response)


@app.get("/api/orders")
def order_status(response: Response):
    return _journey("orders", response)


@app.post("/api/checkout")
def checkout(response: Response):
    """Der längste Pfad: neun Services, drei externe Systeme, sechs Datenbanken."""
    basket = round(random.uniform(19.9, 480.0), 2)
    span = trace.get_current_span()
    span.set_attribute("cart.value_eur", basket)
    span.set_attribute("cart.items", random.randint(1, 6))

    result = _journey("checkout", response, {"cart_value_eur": basket})
    if result["status"] == "error":
        orders_failed.add(1, {"reason": result["failed_service"]})
        return result

    cart_value.record(basket)
    orders_created.add(1)
    order_revenue.add(basket)
    logger.info("Bestellung abgeschlossen, Warenkorbwert %.2f EUR", basket)
    return result


# --- Steuerung der Demo ------------------------------------------------------
@app.get("/chaos")
def chaos_status():
    active = topology.chaos.active
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
    detail = topology.chaos.set(scenario)
    logger.warning("Chaos-Szenario umgeschaltet auf '%s' (%s)", scenario, detail["label"])
    return {"active": scenario, "detail": detail}


# --- Kompatibilitaet zu den urspruenglichen PoC-Endpoints ---------------------
@app.get("/normal")
def normal_request():
    time.sleep(random.uniform(0.01, 0.05))
    logger.info("Normal request verarbeitet")
    return {"status": "ok"}


@app.get("/error")
def error_request(response: Response):
    time.sleep(random.uniform(0.1, 0.5))
    if random.random() < 0.7:
        response.status_code = 500
        logger.error("SIMULIERTER FEHLER: Datenbank-Verbindung fehlgeschlagen!")
        return {"status": "error", "message": "Simulated failure"}
    return {"status": "ok", "message": "Lucky this time"}
