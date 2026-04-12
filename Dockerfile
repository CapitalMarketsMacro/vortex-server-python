# ── Vortex Data Server ──────────────────────────────────────────────────────
# perspective-python ships prebuilt wheels for linux/amd64 and linux/arm64
# on python:3.11-slim (glibc ≥ 2.28), so no cmake/build-essential needed.
#
# All runtime config comes from VORTEX_* env vars — see .env.example.
# Inject via ConfigMap + Secret (envFrom) in OpenShift / Kubernetes.

FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY vortex/ ./vortex/

EXPOSE 8080

# Env var defaults — override in deployment
ENV VORTEX_HOST=0.0.0.0 \
    VORTEX_PORT=8080 \
    VORTEX_LOG_LEVEL=INFO \
    VORTEX_LOG_FORMAT=json

CMD ["vortex-server"]
