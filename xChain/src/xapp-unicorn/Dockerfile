# docker build -f /home/lapdk/workspace/oai-v210/xChain/src/xapp-unicorn/Dockerfile \
#   -t ddocker122/xchain-unicorn:latest \
#   /home/lapdk/workspace/oai-v210/xChain/src
# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install flask numpy \
    && pip install --no-cache-dir --prefix=/install \
        torch --index-url https://download.pytorch.org/whl/cpu


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN useradd -m xchainuser
USER xchainuser

COPY --from=builder /install /usr/local

COPY xapp-unicorn/xchain_model.py .
COPY xapp/xapp_control.py ./xapp_control.py

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV XCHAIN_PORT=5004
ENV XCHAIN_DATA_PORT=4700
ENV MODEL_DIR=/mnt/model
ENV MODEL_ARCH=ForwConvNet
ENV OOD_INDEX=5
ENV SLICE_LEN=64

CMD ["python", "xchain_model.py"]
