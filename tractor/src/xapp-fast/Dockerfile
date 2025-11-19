# ------------------------------------------------------------
# Stage 1 — Builder (install dependencies cleanly)
# ------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install minimal build tools required for XGBoost wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a temporary directory
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install \
        flask \
        numpy \
        xgboost==3.1.1


# ------------------------------------------------------------
# Stage 2 — Runtime (very small image)
# ------------------------------------------------------------
FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN useradd -m xchainuser
USER xchainuser

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application code
COPY xapp-fast/xchain_model.py .
COPY xapp/xapp_control.py ./xapp_control.py

# Container-optimized Python settings
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Environment variables (overridable in Kubernetes)
ENV XCHAIN_PORT=5001
ENV XCHAIN_DATA_PORT=4400
ENV MODEL_PATH=/mnt/model/xgb_model.json

CMD ["python", "xchain_model.py"]
