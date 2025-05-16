#!/bin/bash

# Check if repodir is provided
if [ -z "$1" ]; then
  echo "Usage: $0 <repodir>"
  exit 1
fi

REPODIR="$1"

# Uninstall existing Helm releases in the 'oai' namespace
echo "Uninstalling existing Helm releases in namespace 'oai'..."
helm uninstall $(helm list -aq -n oai) -n oai
sleep 7

# Deploy oai-5g-basic
echo "Deploying oai-5g-basic..."
cd "$REPODIR/charts/oai-5g-core/oai-5g-basic" || exit 1
helm dependency update
helm install oai-5g-basic . -n oai

# Wait for AMF pod to be ready
echo "Waiting for AMF pod to become ready..."
TIMEOUT=300  # seconds
INTERVAL=5
ELAPSED=0

while true; do
  PODNAME=$(kubectl get pods -l app.kubernetes.io/name=oai-amf -o jsonpath="{.items[*].metadata.name}" -n oai)

  if [ -n "$PODNAME" ]; then
    STATUS=$(kubectl get pod "$PODNAME" -n oai -o jsonpath="{.status.containerStatuses[0].ready}")
    if [ "$STATUS" = "true" ]; then
      echo "AMF pod $PODNAME is ready."
      break
    fi
  fi

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "Timeout waiting for AMF pod to be ready."
    exit 1
  fi

  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

# Deploy oai-cu-cp
echo "Deploying oai-cu-cp..."
cd -
cd "$REPODIR/charts/oai-5g-ran/oai-cu-cp" || exit 1
helm install oai-cu-cp .
sleep 7

# Deploy oai-cu-up
echo "Deploying oai-cu-up..."
helm install oai-cu-up ../oai-cu-up
sleep 7

# Deploy oai-du
echo "Deploying oai-du..."
helm install oai-du ../oai-du
sleep 7

# Deploy oai-nr-ue
echo "Deploying oai-nr-ue..."
helm install oai-nr-ue ../oai-nr-ue
sleep 7

echo "All deployments completed successfully."

