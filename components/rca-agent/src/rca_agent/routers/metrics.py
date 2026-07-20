"""Metrics router placeholder — actual metrics served via mounted ASGI app."""

from fastapi import APIRouter

router = APIRouter()

# Prometheus metrics are mounted at /metrics in main.py via prometheus_client.make_asgi_app()
