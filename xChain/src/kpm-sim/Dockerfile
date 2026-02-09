FROM python:3.10-slim

WORKDIR /app

COPY kpm_sim.py /app/kpm_sim.py

RUN pip install --no-cache-dir numpy

CMD ["python", "kpm_sim.py"]
