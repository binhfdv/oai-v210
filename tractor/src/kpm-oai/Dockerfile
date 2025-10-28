FROM python:3.11-slim

ENV CLEAN_DIR=/data/clean \
    ORCH_HOST=xapp-orchestrator \
    ORCH_PORT=4200 \
    LOG_LEVEL=INFO

WORKDIR /app

RUN pip install --no-cache-dir watchdog

COPY kpm_oai.py /app/kpm_oai.py

EXPOSE 4200

# Run the streamer
ENTRYPOINT ["python3", "/app/kpm_oai.py"]
