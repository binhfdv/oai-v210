#!/bin/bash

set -e  # Exit on error

# Function to uninstall a Helm release if it exists
uninstall_if_exists() {
  local release=$1
  if helm list --short | grep -q "^${release}$"; then
    echo "Uninstalling existing Helm release: $release"
    helm uninstall "$release"
  else
    echo "No existing Helm release named $release"
  fi
}

# Step 1: Uninstall existing charts
uninstall_if_exists "near-rt-ric"
uninstall_if_exists "emu-gnb"
uninstall_if_exists "emu-cu"
uninstall_if_exists "emu-du"
uninstall_if_exists "xapp-kpm-moni"

echo "Waiting for cleanup to complete..."
sleep 7

# Step 2: Install charts
echo "Installing near-rt-ric..."
helm install near-rt-ric ./nearrt-ric

echo "Waiting for near-rt-ric pod to become ready..."
TIMEOUT=300  # seconds
INTERVAL=5
ELAPSED=0

while true; do
  PODNAME=$(kubectl get pods -l app.kubernetes.io/name=oai-nearrt-ric -o jsonpath="{.items[*].metadata.name}" -n oai)

  if [ -n "$PODNAME" ]; then
    STATUS=$(kubectl get pod "$PODNAME" -n oai -o jsonpath="{.status.containerStatuses[0].ready}")
    if [ "$STATUS" = "true" ]; then
      echo "near-rt-ric pod $PODNAME is ready."
      break
    fi
  fi

  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "Timeout waiting for near-rt-ric pod to be ready."
    exit 1
  fi

  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo "Installing emu-gnb..."
helm install emu-gnb ./emu-gnb-mono

echo "Installing emu-cu..."
helm install emu-cu ./emu-cu

echo "Installing emu-du..."
helm install emu-du ./emu-du

echo "Installing xapp-kpm-moni..."
helm install xapp-kpm-moni ./xapp-kpm-moni

echo "Deployment complete."
