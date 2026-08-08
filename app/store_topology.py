"""Service-Landschaft des stationaeren Filialbetriebs (Einstiegspunkt: store-api).

Deckt Kasse, Filiallager, Zentrallager/WMS, Nachschub, Logistik und Facility ab.
Ueber Click & Collect und die gemeinsam genutzten Services (pricing, loyalty,
payment) haengt die Filiale am selben Backbone wie der Onlineshop - in der
Service-Landkarte wachsen beide Welten dadurch zu einer Landschaft zusammen.
"""

from __future__ import annotations

from simulation import Call, Chaos, count_services, db, device, execute

ENTRY_SERVICE = "store-api"

# --- Datenhaltung ------------------------------------------------------------
STORE_STOCK_DB = db("store-stock-db", "postgresql", 5, 10)
WMS_DB = db("wms-db", "postgresql", 7, 15)
WORKFORCE_DB = db("workforce-db", "postgresql", 4, 8)
FORECAST_STORE = db("forecast-store", "clickhouse", 9, 22)
PRICING_DB = db("pricing-db", "postgresql", 3, 6)
LOYALTY_DB = db("loyalty-db", "postgresql", 3, 6)
RETURNS_DB = db("returns-db", "postgresql", 4, 8)

# --- Hardware und externe Schnittstellen -------------------------------------
CARD_TERMINAL = device("card-terminal", "authorize", 60, 90)
FISCAL_PRINTER = device("fiscal-printer", "print", 25, 40)
TAX_AUTHORITY = device("tax-authority-api", "signReceipt", 45, 70)
BARCODE_SCANNER = device("handheld-scanner", "scan", 8, 14)
ROBOTICS = device("warehouse-robotics", "moveTote", 40, 80)
FLEET_TELEMATICS = device("fleet-telematics", "getPosition", 30, 55)
ESL_GATEWAY = device("esl-gateway", "pushPrice", 18, 40)
IOT_GATEWAY = device("iot-gateway", "readSensors", 12, 30)
DOCUMENT_ARCHIVE = device("document-archive", "store", 20, 35)

# --- Gemeinsam genutzte Konzern-Services -------------------------------------
PRICING = Call("pricing-service", "GetPrices", 5, 9, children=(PRICING_DB,))
LOYALTY = Call("loyalty-service", "AddPoints", 4, 8, children=(LOYALTY_DB,))

# --- Filiale -----------------------------------------------------------------
STORE_INVENTORY = Call(
    "store-inventory-service", "AdjustStock", 6, 12, children=(STORE_STOCK_DB,)
)
RECEIPT = Call(
    "receipt-service", "IssueReceipt", 6, 10,
    children=(FISCAL_PRINTER, TAX_AUTHORITY, DOCUMENT_ARCHIVE),
)
POS = Call(
    "pos-service", "RingUpBasket", 8, 15,
    children=(PRICING, CARD_TERMINAL, RECEIPT, LOYALTY, STORE_INVENTORY),
)
SHELF_LABEL = Call(
    "shelf-label-service", "SyncPrices", 7, 14, children=(PRICING, ESL_GATEWAY)
)
STAFF = Call(
    "staff-scheduling-service", "PlanShifts", 9, 18, children=(WORKFORCE_DB,)
)
ENERGY = Call(
    "energy-monitoring-service", "CollectReadings", 6, 14, children=(IOT_GATEWAY,)
)

# --- Lager und Logistik ------------------------------------------------------
PICK_PACK = Call(
    "pick-pack-service", "PickItems", 12, 25, children=(ROBOTICS, BARCODE_SCANNER)
)
WMS = Call(
    "warehouse-management-service", "ReserveStock", 10, 20,
    children=(WMS_DB, PICK_PACK),
)
DEMAND_FORECAST = Call(
    "demand-forecast-service", "PredictDemand", 25, 55, children=(FORECAST_STORE,)
)
ROUTE_OPTIMIZER = Call("route-optimizer-service", "PlanRoute", 30, 70)
LOGISTICS = Call(
    "logistics-service", "DispatchDelivery", 11, 20,
    children=(ROUTE_OPTIMIZER, FLEET_TELEMATICS),
)
GOODS_RECEIPT = Call(
    "goods-receipt-service", "BookIncoming", 9, 18,
    children=(BARCODE_SCANNER, WMS, STORE_INVENTORY),
)
RETURNS = Call(
    "returns-service", "ProcessReturn", 8, 16,
    children=(RETURNS_DB, STORE_INVENTORY, RECEIPT),
)
CLICK_COLLECT_PICKING = Call(
    "click-collect-service", "PreparePickup", 8, 15,
    children=(STORE_INVENTORY, PICK_PACK),
)

JOURNEYS: dict[str, tuple[Call, ...]] = {
    # Kundenverkehr waehrend der Oeffnungszeiten
    "pos-checkout": (POS,),
    "returns": (RETURNS,),
    "click-collect": (CLICK_COLLECT_PICKING,),
    "price-check": (PRICING, STORE_INVENTORY),
    # Filialbetrieb
    "goods-receipt": (GOODS_RECEIPT,),
    "shelf-labels": (SHELF_LABEL,),
    "staff-planning": (STAFF,),
    "facility": (ENERGY,),
    # Nachtbetrieb: Nachschub, Disposition, Inventur
    "replenishment": (DEMAND_FORECAST, WMS, LOGISTICS),
    "stocktaking": (STORE_INVENTORY, WMS, BARCODE_SCANNER),
}

SCENARIOS: dict[str, dict] = {
    "normal": {"label": "Normalbetrieb", "targets": {}},
    "terminal-down": {
        "label": "Kartenterminals der Filiale gestoert",
        "targets": {"card-terminal": {"latency_ms": 1800, "fail_rate": 0.45}},
    },
    "wms-degraded": {
        "label": "Lagerverwaltung ueberlastet",
        "targets": {
            "wms-db": {"latency_ms": 800, "fail_rate": 0.08},
            "warehouse-robotics": {"latency_ms": 600, "fail_rate": 0.05},
        },
    },
    "fiscal-outage": {
        "label": "Fiskalschnittstelle nicht erreichbar",
        "targets": {"tax-authority-api": {"latency_ms": 2200, "fail_rate": 0.60}},
    },
    "logistics-delay": {
        "label": "Routenoptimierung antwortet nicht",
        "targets": {"route-optimizer-service": {"latency_ms": 1500, "fail_rate": 0.12}},
    },
}

chaos = Chaos(SCENARIOS)


def run_journey(name: str, record) -> None:
    for call in JOURNEYS[name]:
        execute(call, ENTRY_SERVICE, record, chaos)


def service_count() -> int:
    return count_services(JOURNEYS) + 1  # + store-api
