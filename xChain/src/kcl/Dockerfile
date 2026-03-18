# docker build -f Dockerfile -t ddocker122/xchain-kcl:latest .
FROM python:3.11-slim

ENV LISTEN_PORT=4500 \
    MODELS_DIR=/models \
    LABELING_MODEL=labeling_xapp.pth \
    RESOURCE_MODEL=resource_xapp.pth \
    SCALER_FILE=scaler.pkl \
    LOG_LEVEL=INFO

WORKDIR /app

# Install torch CPU-only, then pyg (no torch_cluster, no torch_sparse — not needed for SAGEConv)
# All in one RUN layer so intermediate cache is not committed
RUN pip install --no-cache-dir \
        torch==2.1.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
        torch_geometric \
        torch_scatter \
        -f https://data.pyg.org/whl/torch-2.1.0+cpu.html \
    && pip install --no-cache-dir \
        scikit-learn \
        "numpy<2" \
        pandas \
    && find /usr/local/lib/python3.11 -name "*.pyc"      -delete \
    && find /usr/local/lib/python3.11 -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null; true \
    && rm -rf /root/.cache /tmp/*

COPY xapp_kcl.py /app/xapp_kcl.py

EXPOSE 4500

ENTRYPOINT ["python3", "/app/xapp_kcl.py"]
