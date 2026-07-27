"""OpenTelemetry tracing — OTLP → opentelemetry-collector → Coroot + Instana."""

from __future__ import annotations

import os
import sys


def _log(msg: str) -> None:
    print(f"[otel] {msg}", file=sys.stderr, flush=True)


def init_tracing(service_name: str) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        _log("disabled: OTEL_EXPORTER_OTLP_ENDPOINT empty")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        name = os.getenv("OTEL_SERVICE_NAME", service_name).strip() or service_name
        provider = TracerProvider(resource=Resource.create({SERVICE_NAME: name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(insecure=True)))
        trace.set_tracer_provider(provider)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().instrument()
        except Exception as exc:  # noqa: BLE001
            _log(f"httpx instrument skip: {exc}")

        _log(f"tracing enabled service={name} endpoint={endpoint}")
    except Exception as exc:  # noqa: BLE001
        _log(f"init FAILED: {exc}")


def instrument_fastapi(app, service_name: str) -> None:
    init_tracing(service_name)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _log(f"fastapi instrumented service={service_name}")
    except Exception as exc:  # noqa: BLE001
        _log(f"fastapi instrument FAILED: {exc}")
