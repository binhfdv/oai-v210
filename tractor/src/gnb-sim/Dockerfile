FROM python:3.10-slim

WORKDIR /app

COPY gnb_sim.py /app/gnb_sim.py

RUN pip install --no-cache-dir numpy

CMD ["python", "gnb_sim.py"]
