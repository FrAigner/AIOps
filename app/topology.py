"""Service-Landschaft des Onlineshops (Einstiegspunkt: poc-api)."""

from __future__ import annotations

from simulation import Call, Chaos, count_services, db, device, execute

ENTRY_SERVICE = "poc-api"

# --- Datenhaltung ------------------------------------------------------------
PRODUCT_DB = db("product-db", "postgresql", 5, 9)
REVIEW_DB = db("review-db", "postgresql", 4, 7)
USER_DB = db("user-db", "postgresql", 4, 6)
ORDER_DB = db("order-db", "postgresql", 6, 11)
WAREHOUSE_DB = db("warehouse-db", "postgresql", 7, 14)
PRICING_DB = db("pricing-db", "postgresql", 3, 6)
PROMOTION_DB = db("promotion-db", "postgresql", 3, 5)
LOYALTY_DB = db("loyalty-db", "postgresql", 3, 6)
LEDGER_DB = db("ledger-db", "postgresql", 5, 9)
REDIS = db("redis-cache", "redis", 1, 3)
ELASTIC = db("elasticsearch", "elasticsearch", 12, 30)

# --- Externe Anbieter --------------------------------------------------------
PAYMENT_PROVIDER = device("payment-provider-psp", "authorize", 55, 60)
CARRIER_API = device("carrier-api", "createLabel", 30, 50)
EMAIL_PROVIDER = device("email-provider", "send", 18, 35)
SMS_PROVIDER = device("sms-provider", "send", 20, 40)

# --- Fachliche Services ------------------------------------------------------
ML_INFERENCE = Call("ml-inference-service", "Predict", 22, 45)
USER_PROFILE = Call("user-profile-service", "GetProfile", 6, 10, children=(USER_DB,))
PRICING = Call("pricing-service", "GetPrices", 5, 9, children=(PRICING_DB,))
REVIEWS = Call("review-service", "GetReviews", 6, 12, children=(REVIEW_DB,))
CATALOG = Call("catalog-service", "GetProducts", 7, 14, children=(PRODUCT_DB,))
SEARCH = Call("search-service", "Query", 9, 18, children=(ELASTIC,))
RECOMMENDATION = Call(
    "recommendation-service", "GetRecommendations", 8, 16,
    children=(USER_PROFILE, ML_INFERENCE),
)
CART = Call("cart-service", "GetCart", 4, 8, children=(REDIS,))
INVENTORY = Call("inventory-service", "CheckStock", 8, 16, children=(WAREHOUSE_DB,))
PROMOTION = Call("promotion-service", "ApplyCoupons", 5, 10, children=(PROMOTION_DB,))
FRAUD = Call("fraud-detection-service", "Score", 12, 22, children=(ML_INFERENCE,))
LEDGER = Call("ledger-service", "Book", 8, 14, children=(LEDGER_DB,))
PAYMENT = Call("payment-service", "Charge", 10, 18, children=(PAYMENT_PROVIDER, LEDGER))
NOTIFICATION = Call(
    "notification-service", "SendConfirmation", 5, 9,
    children=(EMAIL_PROVIDER, SMS_PROVIDER),
)
SHIPPING = Call("shipping-service", "ScheduleDelivery", 9, 15, children=(CARRIER_API,))
LOYALTY = Call("loyalty-service", "AddPoints", 4, 8, children=(LOYALTY_DB,))
ORDER = Call("order-service", "CreateOrder", 9, 16, children=(ORDER_DB, NOTIFICATION))

JOURNEYS: dict[str, tuple[Call, ...]] = {
    "home": (CATALOG, RECOMMENDATION, REVIEWS),
    "search": (SEARCH, CATALOG, PRICING),
    "product": (CATALOG, INVENTORY, REVIEWS, RECOMMENDATION),
    "cart": (CART, INVENTORY, PRICING),
    "checkout": (
        CART, PRICING, PROMOTION, FRAUD, INVENTORY, PAYMENT, ORDER, SHIPPING, LOYALTY,
    ),
    "orders": (
        Call("order-service", "GetOrder", 7, 12, children=(ORDER_DB,)),
        Call("shipping-service", "TrackShipment", 8, 14, children=(CARRIER_API,)),
    ),
}

SCENARIOS: dict[str, dict] = {
    "normal": {"label": "Normalbetrieb", "targets": {}},
    "latency": {
        "label": "Payment-Provider antwortet langsam",
        "targets": {"payment-provider-psp": {"latency_ms": 900, "fail_rate": 0.02}},
    },
    "errors": {
        "label": "Warehouse-DB faellt teilweise aus",
        "targets": {"warehouse-db": {"latency_ms": 60, "fail_rate": 0.30}},
    },
    "search-degraded": {
        "label": "Elasticsearch-Cluster ueberlastet",
        "targets": {"elasticsearch": {"latency_ms": 1200, "fail_rate": 0.05}},
    },
    "ml-degraded": {
        "label": "ML-Inferenz laeuft ins Timeout",
        "targets": {"ml-inference-service": {"latency_ms": 700, "fail_rate": 0.03}},
    },
    "outage": {
        "label": "Teilausfall der Zahlungsstrecke",
        "targets": {
            "payment-provider-psp": {"latency_ms": 2500, "fail_rate": 0.75},
            "ledger-service": {"latency_ms": 400, "fail_rate": 0.10},
        },
    },
}

chaos = Chaos(SCENARIOS)


def run_journey(name: str, record) -> None:
    for call in JOURNEYS[name]:
        execute(call, ENTRY_SERVICE, record, chaos)


def service_count() -> int:
    return count_services(JOURNEYS) + 1  # + poc-api
