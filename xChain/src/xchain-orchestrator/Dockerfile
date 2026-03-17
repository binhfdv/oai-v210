FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir flask requests
COPY orchestrator.py .

CMD ["python", "orchestrator.py"]
