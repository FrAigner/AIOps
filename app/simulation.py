"""Gemeinsame Mechanik für die simulierten Service-Landschaften.

Jeder Knoten bekommt einen eigenen TracerProvider mit eigener service.name-
Resource. Dadurch entstehen echte Client/Server-Span-Paare - und Tempo leitet
daraus eine mehrstufige Service-Landkarte ab statt nur flacher Virtual Nodes.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

# Grundrauschen: sehr seltene Fehler, damit das SLO im Normalbetrieb grün bleibt.
BASE_FAIL_RATE = 0.0008

_providers: dict[str, TracerProvider] = {}


def tracer_for(service: str):
    """Ein TracerProvider je Service - so trägt jeder Span die richtige Identität."""
    if service not in _providers:
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": service, "service.namespace": "retail"}
            )
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        _providers[service] = provider
    return _providers[service].get_tracer("topology-simulator")


class DownstreamError(RuntimeError):
    """Fehler eines simulierten Downstream-Systems."""

    def __init__(self, service: str):
        super().__init__(f"{service} unavailable")
        self.service = service


@dataclass(frozen=True)
class Call:
    service: str
    operation: str
    base_ms: float
    jitter_ms: float
    children: tuple = ()
    # Externe Systeme ohne eigene Instrumentierung (DB, SaaS, Hardware) erscheinen
    # in der Landkarte als Endknoten - genau wie in einer echten Umgebung.
    external: bool = False
    db_system: str | None = None
    base_fail: float = 0.0
    tier: str = "application"


def db(name: str, system: str, base: float = 5.0, jitter: float = 9.0) -> Call:
    return Call(
        name, "query", base, jitter, external=True, db_system=system, tier="datastore"
    )


def device(name: str, operation: str, base: float, jitter: float) -> Call:
    """Hardware oder externe Schnittstelle ohne eigene Telemetrie."""
    return Call(name, operation, base, jitter, external=True, tier="device")


class Chaos:
    """Schaltbare Störungsszenarien einer Landschaft."""

    def __init__(self, scenarios: dict[str, dict]):
        self.scenarios = scenarios
        self._active = "normal"

    @property
    def active(self) -> str:
        return self._active

    def set(self, name: str) -> dict:
        self._active = name
        return self.scenarios[name]

    def impact(self, service: str) -> tuple[float, float]:
        target = self.scenarios[self._active]["targets"].get(service)
        if not target:
            return 0.0, 0.0
        return target.get("latency_ms", 0.0), target.get("fail_rate", 0.0)


def execute(call: Call, caller: str, record, chaos: Chaos) -> None:
    """Führt einen Aufruf aus: Client-Span beim Aufrufer, Server-Span beim Ziel."""
    extra_ms, chaos_fail = chaos.impact(call.service)
    started = time.perf_counter()

    client = tracer_for(caller)
    with client.start_as_current_span(
        f"{call.service}/{call.operation}", kind=SpanKind.CLIENT
    ) as cspan:
        cspan.set_attribute("peer.service", call.service)
        if call.db_system:
            cspan.set_attribute("db.system", call.db_system)
            cspan.set_attribute("db.operation", call.operation)

        if call.external:
            _work(call, extra_ms)
            _maybe_fail(call, chaos_fail)
        else:
            server = tracer_for(call.service)
            with server.start_as_current_span(
                call.operation, kind=SpanKind.SERVER
            ) as sspan:
                sspan.set_attribute("service.tier", call.tier)
                _work(call, extra_ms)
                for child in call.children:
                    execute(child, call.service, record, chaos)
                _maybe_fail(call, chaos_fail)

        record(call.service, (time.perf_counter() - started) * 1000)


def _work(call: Call, extra_ms: float) -> None:
    time.sleep((call.base_ms + random.uniform(0, call.jitter_ms) + extra_ms) / 1000)


def _maybe_fail(call: Call, chaos_fail: float) -> None:
    if random.random() < max(chaos_fail, call.base_fail, BASE_FAIL_RATE):
        trace.get_current_span().set_status(
            Status(StatusCode.ERROR, f"{call.service} nicht erreichbar")
        )
        raise DownstreamError(call.service)


def count_services(journeys: dict[str, tuple[Call, ...]]) -> int:
    names: set[str] = set()

    def walk(c: Call) -> None:
        names.add(c.service)
        for child in c.children:
            walk(child)

    for calls in journeys.values():
        for call in calls:
            walk(call)
    return len(names)
