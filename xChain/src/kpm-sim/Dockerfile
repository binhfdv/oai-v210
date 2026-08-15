# docker build -t ddocker122/tractor-kpm-simu:latest /home/lapdk/workspace/oai-v210/xChain/src/kpm-sim/

FROM python:3.10-slim

WORKDIR /app

COPY kpm_sim.py /app/kpm_sim.py

RUN pip install --no-cache-dir numpy

CMD ["python", "kpm_sim.py"]
