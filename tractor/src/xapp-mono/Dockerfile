# # Dockerfile
# # FROM python:3.10-slim
# FROM python:3.11-slim

# # Default envs
# ENV MODEL_PATH=/mnt/model/model.pt
# ENV NORM_PATH=/mnt/model/norm.pkl

# WORKDIR /app


# COPY xapp-mono/main.py /app/main.py
# COPY xapp-mono/app_server.py /app/app_server.py
# # COPY xapp-mono/orchestrator.py /app/orchestrator.py
# COPY xapp-mono/orchestrator_multi_ue.py /app/orchestrator.py

# COPY xapp/xapp_control.py /app/xapp_control.py
# COPY xapp/python /app/python


# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     libjpeg-dev \
#     libfreetype6-dev \
#     libblas-dev \
#     liblapack-dev \
#     && rm -rf /var/lib/apt/lists/*



# RUN pip install --no-cache-dir flask numpy torch matplotlib pandas


# # Expose HTTP port for API and TCP port for orchestration control
# EXPOSE 5000 4200

# CMD ["python", "main.py"]

# =========================
# Stage 1: Build dependencies
# =========================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install only what's needed to build Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pre-install Python packages in a temporary layer
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        flask \
        numpy \
        matplotlib \
        pandas \
        torch==2.3.0+cpu -f https://download.pytorch.org/whl/torch_stable.html

# =========================
# Stage 2: Final runtime
# =========================
FROM python:3.11-slim

# Default environment variables
ENV MODEL_PATH=/mnt/model/model.pt
ENV NORM_PATH=/mnt/model/norm.pkl

WORKDIR /app

# Copy pre-installed packages from builder
COPY --from=builder /usr/local /usr/local

# Copy application files
COPY xapp-mono/main.py /app/main.py
COPY xapp-mono/app_server.py /app/app_server.py
# COPY xapp-mono/orchestrator.py /app/orchestrator.py
COPY xapp-mono/orchestrator_multi_ue.py /app/orchestrator.py
COPY xapp/xapp_control.py /app/xapp_control.py
COPY xapp/python /app/python

# Expose ports
EXPOSE 5000 4200

# Run the app
CMD ["python", "main.py"]
