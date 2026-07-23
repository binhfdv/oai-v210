# docker build \
#   -f /home/lapdk/workspace/oai-v210/xChain/src/xapp-agent/Dockerfile \
#   -t ddocker122/xchain-agent:latest \
#   /home/lapdk/workspace/oai-v210/xChain/src
# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY xapp-agent/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

RUN useradd -m xchainuser
USER xchainuser

COPY --from=builder /install /usr/local

COPY xapp-agent/universal_agent.py .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV AGENT_MODE=preprocessing
ENV AGENT_PORT=5100
ENV AGENT_DATA_PORT=4301
ENV MODEL_HOST=localhost
ENV MODEL_PORT=5000
ENV PEER_AGENT_HOST=""
ENV PEER_AGENT_PORT=5101
ENV CONTEXT_LABEL=urllc-mmtc
ENV DRIFT_DETECTOR=ddm
ENV URLLC_CLASS=URLLC

CMD ["python", "universal_agent.py"]
