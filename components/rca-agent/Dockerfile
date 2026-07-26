# syntax=docker/dockerfile:1

# --- Build stage ---
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip wheel --no-cache-dir --wheel-dir /wheels .

# --- Runtime stage ---
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="rca-agent" \
      org.opencontainers.image.description="RCA Agent for Open Source AIOps Platform" \
      org.opencontainers.image.version="0.1.0-skeleton"

ARG KUBECTL_VERSION=v1.29.14

# OpenShift runs with arbitrary UID — ensure writable dirs
# kubectl: python WS exec hits None.decode on this lab; kubectl exec is reliable
RUN groupadd -r aiops && useradd -r -g aiops -d /app -s /sbin/nologin aiops \
    && mkdir -p /app /tmp \
    && chown -R aiops:aiops /app /tmp \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
         -o /usr/local/bin/kubectl \
    && chmod 0755 /usr/local/bin/kubectl \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl \
    && rm -rf /wheels

USER aiops

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/live')"

CMD ["python", "-m", "uvicorn", "rca_agent.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
