# -------------------------------
# Stage 1 — builder (installs deps)
# -------------------------------
# docker build \
#   -f xChain/src/smartGW/Dockerfile \
#   -t ddocker122/xchain-smartgw:latest \
#   xChain/src/

FROM python:3.11-slim AS builder

WORKDIR /app

# Install minimal build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a clean directory
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefix=/install \
        flask \
        requests \
        numpy \
        scikit-learn==1.6.1


# -------------------------------
# Stage 2 — runtime (very small)
# -------------------------------
FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN useradd -m smartgwuser
USER smartgwuser

# Copy installed Python packages
COPY --from=builder /install /usr/local

# Copy application code
COPY smartGW/smartgw_server.py .
COPY xapp/xapp_control.py /app/xapp_control.py

# KPM TCP listener + Flask debug endpoint
EXPOSE 4200 5004

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV ORCH_HOST=xchain-orchestrator
ENV ORCH_PORT=5010
ENV ORCH_POLL_INTERVAL=30

ENV KPM_COL_THPDL=13
ENV KPM_COL_THPUL=20
ENV KPM_COL_VOLUL=32

CMD ["python", "smartgw_server.py"]
