# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install \
        flask \
        numpy \
        scikit-learn \
        torch --index-url https://download.pytorch.org/whl/cpu


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN useradd -m xchainuser
USER xchainuser

COPY --from=builder /install /usr/local

COPY xapp-lstm/xchain_model.py .
COPY xapp/xapp_control.py ./xapp_control.py

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV XCHAIN_PORT=5002
ENV XCHAIN_DATA_PORT=4600
ENV MODEL_DIR=/mnt/model
ENV T=32

CMD ["python", "xchain_model.py"]
