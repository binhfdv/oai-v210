# docker build \
#   -f xChain/src/xchain-orchestrator/Dockerfile \
#   -t ddocker122/xchain-orchestrator:latest \
#   xChain/src/xchain-orchestrator/
FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir flask requests
COPY orchestrator.py .

CMD ["python", "orchestrator.py"]
