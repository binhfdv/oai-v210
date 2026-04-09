# Stage 1: Build Angular GUI
FROM node:20-alpine AS gui-build
WORKDIR /app
COPY gui/package*.json ./
RUN npm install
COPY gui/ ./
RUN npm run build

# Stage 2: Python API server
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends bash && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy API server sources
COPY api/server/ ./

# Copy Angular build output from stage 1
# Angular outputs to ../api/server/templates (relative to gui/), which is /api/server/templates in stage 1
COPY --from=gui-build /api/server/templates ./templates

# Install Python dependencies
RUN pip install --no-cache-dir \
    Flask \
    Flask-SocketIO \
    flask-cors \
    watchdog \
    numpy \
    matplotlib \
    scipy \
    pandas

# Environment variables — all configurable via helm chart
ENV BASE_DIR=/results/
ENV REFRESH_INTERVAL=2
ENV SOCKET_PORT=4000
ENV TRAFFIC_SERVER_HOSTNAME=oai-traffic-server
ENV TRAFFIC_SERVER_CMD_VR="start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/vr.pcap"
ENV TRAFFIC_SERVER_CMD_HAPTIC="start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/haptic.pcap"
ENV TRAFFIC_SERVER_CMD_SOCIAL="start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/social.pcap"
ENV TRAFFIC_SERVER_CMD_IOT="start:/usr/local/bin/tcpreplay -i eth0 /demo/pcap/iot.pcap"
ENV SMARTGW_HOSTNAME=xchain-smartgw-demo
ENV SMARTGW_CMD_MODELS="start:{models}"

EXPOSE 5000

CMD ["python", "api_server.py"]
