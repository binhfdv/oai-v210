FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping iproute2 tcpdump netcat-openbsd curl tcpreplay \
    automake build-essential libpcap-dev python3 python3-pip \
    && pip3 install scapy \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY universal_agent.py ./

# Environment variables — all configurable via helm chart
ENV DEMO_SERVER_HOST=""
ENV DEMO_SERVER_PORT=4000
ENV AGENT_MODE=""

# file mode
ENV AGENT_OUTPUT_FILE=/tmp/selected_models.txt

# log_collector mode
ENV MODEL_NAME=""
ENV MODEL_TYPE=""
ENV LOG_FILE=/model-logs/model.log
ENV RESULTS_DIR=/results

CMD ["python", "universal_agent.py"]
