FROM python:3.11-slim

ENV WATCH_NAMESPACE=oai

WORKDIR /app

COPY kpm_log_watcher.py .

RUN pip install --no-cache-dir kubernetes

# Directory to store output CSVs
VOLUME ["/data"]

CMD ["python", "kpm_log_watcher.py"]
