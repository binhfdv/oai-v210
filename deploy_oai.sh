#!/bin/bash

# Usage check
if [ -z "$1" ]; then
  echo "Usage: $0 <repodir> [--c] [components...]"
  echo "Components: core | cu | gnb | ric"
  echo "Options:"
  echo "  --c    Continue deployment (skip helm uninstall)"
  exit 1
fi

REPODIR="$1"
shift

# Check for --c flag
SKIP_UNINSTALL=false
COMPONENTS=()

for arg in "$@"; do
  if [ "$arg" == "--c" ]; then
    SKIP_UNINSTALL=true
  else
    COMPONENTS+=("$arg")
  fi
done

if [ ${#COMPONENTS[@]} -eq 0 ]; then
  echo "Error: No components specified for deployment."
  exit 1
fi

# Common function
wait_for_pod_ready() {
  local LABEL="$1"
  local NAME="$2"
  local TIMEOUT=300
  local INTERVAL=5
  local ELAPSED=0

  echo "Waiting for $NAME pod to become ready..."

  while true; do
    PODNAME=$(kubectl get pods -l app.kubernetes.io/name="$LABEL" -o jsonpath="{.items[*].metadata.name}" -n oai)

    if [ -n "$PODNAME" ]; then
      STATUS=$(kubectl get pod "$PODNAME" -n oai -o jsonpath="{.status.containerStatuses[0].ready}")
      if [ "$STATUS" = "true" ]; then
        echo "$NAME pod $PODNAME is ready."
        break
      fi
    fi

    if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
      echo "Timeout waiting for $NAME pod to be ready."
      exit 1
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
  done
}

# Optionally clean environment
if ! $SKIP_UNINSTALL; then
  echo "Uninstalling existing Helm releases in namespace 'oai'..."
  helm uninstall $(helm list -aq -n oai) -n oai
  sleep 10
else
  echo "Skipping Helm uninstall (--c flag active)"
fi

# Loop through requested components
for COMPONENT in "${COMPONENTS[@]}"; do
  case "$COMPONENT" in
    core)
      echo "Deploying 5G Core..."
      cd "$REPODIR/charts/oai-5g-core/oai-5g-basic" || exit 1
      helm dependency update
      helm install oai-5g-basic . -n oai
      wait_for_pod_ready oai-amf AMF
      ;;

    cu)
      echo "Deploying CU-CP..."
      cd -
      cd "$REPODIR/charts/oai-5g-ran/oai-cu-cp" || exit 1
      helm install oai-cu-cp .
      sleep 7

      echo "Deploying CU-UP..."
      helm install oai-cu-up ../oai-cu-up
      sleep 7

      echo "Deploying DU..."
      helm install oai-du ../oai-du
      sleep 7
      ;;

    gnb)
      echo "Deploying gNB (e2-gnb)..."
      cd -
      cd "$REPODIR/helm-flexric" || exit 1
      helm install e2-gnb ./e2-gnb
      sleep 7
      ;;

    ue)
      echo "Deploying oai-nr-ue..."
      cd -
      cd "$REPODIR/charts/oai-5g-ran/oai-cu-cp" || exit 1
      helm install oai-nr-ue ../oai-nr-ue
      sleep 7
      ;;

    ue-gnb)
      echo "Deploying oai-nr-ue-gnb..."
      cd -
      cd "$REPODIR/charts/oai-5g-ran/oai-cu-cp" || exit 1
      helm install oai-nr-ue-gnb ../oai-nr-ue-gnb
      sleep 7
      ;;

    ric)
      echo "Deploying near-RT-RIC..."
      cd -
      cd "$REPODIR/helm-flexric" || exit 1
      helm install near-rt-ric ./nearrt-ric
      wait_for_pod_ready oai-nearrt-ric near-rt-ric
      ;;

    kpm)
      echo "Deploying xapp-kpm-moni..."
      cd -
      cd "$REPODIR/helm-flexric" || exit 1
      helm install xapp-kpm-moni ./xapp-kpm-moni
      sleep 7
      ;;

    gmrp)
      echo "Deploying xapp-gtp-mac-rlc-pdcp-moni..."
      cd -
      cd "$REPODIR/helm-flexric" || exit 1
      helm install xapp-gtp-mac-rlc-pdcp-moni ./xapp-gtp-mac-rlc-pdcp-moni
      sleep 7
      ;;

    rc)
      echo "Deploying xapp-rc-moni..."
      cd -
      cd "$REPODIR/helm-flexric" || exit 1
      helm install xapp-rc-moni ./xapp-rc-moni
      sleep 7
      ;;

    *)
      echo "Unknown component: $COMPONENT"
      echo "Valid options: core | cu | gnb | ue | ric"
      exit 1
      ;;
  esac
done

echo "Deployment of component(s) ${COMPONENTS[*]} completed successfully."
