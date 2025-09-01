FROM python:3.10-slim

WORKDIR /app

COPY traffic_gen.py /app/

RUN pip install --no-cache-dir argparse

CMD ["python", "traffic_gen.py", "--ip", "--file", "/app/traffic.csv"]
