# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir hatchling
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="incident-api" \
      org.opencontainers.image.version="0.2.0"
RUN groupadd -r aiops && useradd -r -g aiops -d /app -s /sbin/nologin aiops \
    && mkdir -p /app /tmp \
    && chown -R aiops:aiops /app /tmp
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER aiops
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "incident_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
