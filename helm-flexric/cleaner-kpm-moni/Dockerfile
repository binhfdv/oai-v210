FROM python:3.11-slim

WORKDIR /app

COPY cleaner-kpm-moni.py /app/cleaner-kpm-moni.py

RUN pip install --no-cache-dir watchdog

ENV RAW_DIR=/data/raw \
    CLEAN_DIR=/data/clean \
    LOG_LEVEL=INFO

CMD ["python3", "/app/cleaner-kpm-moni.py"]
