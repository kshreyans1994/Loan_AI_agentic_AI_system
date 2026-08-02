# Multi-stage build: keeps the final image free of build toolchains
# (gcc, tesseract build deps) that requirements.txt needs only at install time.

FROM python:3.11-slim AS builder

WORKDIR /build

# Tesseract and its dev headers are needed to build pytesseract's runtime
# dependency correctly on some platforms; poppler-utils backs pdf2image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim

WORKDIR /app

# Runtime-only system deps: tesseract-ocr itself (not just its headers)
# and poppler-utils for pdf2image. No compilers in the final image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Bring in the packages installed in the builder stage
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY app/ ./app/
COPY data/ ./data/
COPY scripts/ ./scripts/

# Runs as non-root — standard expectation for any image ArgoCD/K8s will
# admit under a restrictive PodSecurityPolicy/PSA baseline profile.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness/readiness probes in k8s hit /api/v1/health — see deploy/base/deployment.yaml
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
