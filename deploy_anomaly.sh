#!/bin/bash

# ==============================
# Anomaly Detection Slicing Deployment Script
# Usage: ./deploy_anomaly.sh <repodir> [--c] [components...]
# Components: core | slices | cu | ric | ue | kpm | rc | all
# Options:
#   --c    Continue deployment (skip helm uninstall)
# UE config (env vars, defaults shown):
#   NUM_UES_SLICE1=1   number of UEs on slice1 (dnn=oai1, sd=0x000001)
#   NUM_UES_SLICE2=1   number of UEs on slice2 (dnn=oai2, sd=0x000005)
#   NODE_ROLE=core     Kubernetes node-role label for UE pods
# Example:
#   ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 core slices cu ric
#   NUM_UES_SLICE1=2 NUM_UES_SLICE2=2 ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 ue
#   # Deploy everything in order
#   ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 all

# # Deploy step by step
# ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 core
# ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 --c slices
# ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 --c cu
# ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 --c ric
# ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 --c ue
# ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 --c kpm rc

# # Override UE counts per slice
# NUM_UES_SLICE1=3 NUM_UES_SLICE2=3 ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 --c ue
# Key points:

# all expands to core slices cu ric ue kpm rc in that order
# --c skips uninstall (continue/add components to existing deployment)
# ue delegates to deploy_multi_ue.py with env vars NUM_UES_SLICE1/NUM_UES_SLICE2/NODE_ROLE (defaults: 1/1/core)
# Waits for AMF and near-RT RIC readiness before proceeding; other components use fixed sleeps
# ==============================

# --- Validate input ---
if [ -z "$1" ]; then
  echo "Usage: $0 <repodir> [--c] [components...]"
  echo "Components: core | cu | ric | ue | kpm | rc | all"
  echo "Options: --c  (skip helm uninstall)"
  exit 1
fi

REPODIR="$1"
shift

# --- Parse flags and components ---
SKIP_UNINSTALL=false
COMPONENTS=()

for arg in "$@"; do
  if [ "$arg" == "--c" ]; then
    SKIP_UNINSTALL=true
  elif [ "$arg" == "all" ]; then
    COMPONENTS=(core slices cu ric rc ue) # installation order
  else
    COMPONENTS+=("$arg")
  fi
done

if [ ${#COMPONENTS[@]} -eq 0 ]; then
  echo "Error: No components specified."
  echo "Valid options: core | slices | cu | ric | ue | kpm | rc | all"
  exit 1
fi

# --- UE config (override via env vars) ---
NUM_UES_SLICE1="${NUM_UES_SLICE1:-1}"
NUM_UES_SLICE2="${NUM_UES_SLICE2:-1}"
NODE_ROLE="${NODE_ROLE:-core}"

# --- Paths ---
CORE_DIR="$REPODIR/charts/oai-5g-core/oai-5g-slicing"
SMF_SLICE1_DIR="$REPODIR/charts/oai-5g-core/oai-smf-slice1"
SMF_SLICE2_DIR="$REPODIR/charts/oai-5g-core/oai-smf-slice2"
UPF_SLICE1_DIR="$REPODIR/charts/oai-5g-core/oai-upf-slice1"
UPF_SLICE2_DIR="$REPODIR/charts/oai-5g-core/oai-upf-slice2"
CUCP_DIR="$REPODIR/charts/oai-5g-ran/oai-cu-cp-slice"
CUUP_DIR="$REPODIR/charts/oai-5g-ran/oai-cu-up-slice"
DU_DIR="$REPODIR/charts/oai-5g-ran/oai-du-slice"
UE_DIR="$REPODIR/charts/oai-5g-ran/oai-nr-ue-gnb-slice"
RIC_DIR="$REPODIR/helm-flexric/nearrt-ric"
KPM_DIR="$REPODIR/helm-flexric/xapp-kpm-moni"
RC_DIR="$REPODIR/helm-flexric/xapp-rc-prb-rrc-release"

# --- Helper: wait for pod ready ---
wait_for_pod_ready() {
  local LABEL="$1"
  local NAME="$2"
  local TIMEOUT=300
  local INTERVAL=5
  local ELAPSED=0

  echo "Waiting for $NAME pod to become ready..."

  while true; do
    PODNAME=$(kubectl get pods -l app.kubernetes.io/name="$LABEL" -o jsonpath="{.items[*].metadata.name}" -n oai 2>/dev/null)

    if [ -n "$PODNAME" ]; then
      STATUS=$(kubectl get pod "$PODNAME" -n oai -o jsonpath="{.status.containerStatuses[0].ready}" 2>/dev/null)
      if [ "$STATUS" = "true" ]; then
        echo "$NAME pod $PODNAME is ready."
        break
      fi
    fi

    if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
      echo "Timeout waiting for $NAME to be ready. Continuing anyway..."
      break
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
  done
}

# --- Uninstall existing releases ---
if ! $SKIP_UNINSTALL; then
  echo "Uninstalling existing Helm releases in namespace 'oai'..."
  RELEASES=$(helm list -aq -n oai 2>/dev/null)
  if [ -n "$RELEASES" ]; then
    helm uninstall $RELEASES -n oai
    sleep 10
  else
    echo "No existing releases found."
  fi
else
  echo "Skipping Helm uninstall (--c flag active)"
fi

# --- Deploy components ---
for COMPONENT in "${COMPONENTS[@]}"; do
  case "$COMPONENT" in

    core)
      echo ""
      echo "=== Deploying 5G Core (oai-5g-slicing) ==="
      cd "$CORE_DIR" || exit 1
      helm dependency update
      helm install oai-5g-slicing . -n oai
      wait_for_pod_ready oai-amf AMF
      ;;

    slices)
      echo ""
      echo "=== Deploying SMF slice1 ==="
      cd "$SMF_SLICE1_DIR" || exit 1
      helm install oai-smf-slice1 . -n oai
      wait_for_pod_ready oai-smf-slice1 SMF-Slice1

      echo "=== Deploying SMF slice2 ==="
      cd "$SMF_SLICE2_DIR" || exit 1
      helm install oai-smf-slice2 . -n oai
      wait_for_pod_ready oai-smf-slice2 SMF-Slice2
      sleep 5

      echo "=== Deploying UPF slice1 ==="
      cd "$UPF_SLICE1_DIR" || exit 1
      helm install oai-upf-slice1 . -n oai
      wait_for_pod_ready oai-upf-slice1 UPF-Slice1

      echo "=== Deploying UPF slice2 ==="
      cd "$UPF_SLICE2_DIR" || exit 1
      helm install oai-upf-slice2 . -n oai
      wait_for_pod_ready oai-upf-slice2 UPF-Slice2
      ;;

    ric)
      echo ""
      echo "=== Deploying near-RT RIC ==="
      cd "$RIC_DIR" || exit 1
      helm install near-rt-ric . -n oai
      wait_for_pod_ready oai-nearrt-ric near-RT-RIC
      ;;

    cu)
      echo ""
      echo "=== Deploying CU-CP ==="
      cd "$CUCP_DIR" || exit 1
      helm install oai-cu-cp . -n oai
      wait_for_pod_ready oai-cu-cp CU-CP

      echo "=== Deploying CU-UP ==="
      cd "$CUUP_DIR" || exit 1
      helm install oai-cu-up . -n oai
      wait_for_pod_ready oai-cu-up CU-UP

      echo "=== Deploying DU ==="
      cd "$DU_DIR" || exit 1
      helm install oai-du . -n oai
      wait_for_pod_ready oai-du DU
      ;;

    kpm)
      echo ""
      echo "=== Deploying xApp: KPM monitor ==="
      cd "$KPM_DIR" || exit 1
      helm install xapp-kpm-moni . -n oai
      sleep 7
      ;;

    rc)
      echo ""
      echo "=== Deploying xApp: RC PRB + RRC release ==="
      cd "$RC_DIR" || exit 1
      helm install xapp-rc-prb-rrc-release . -n oai
      sleep 7
      ;;

    ue)
      echo ""
      echo "=== Deploying UEs (slice1=$NUM_UES_SLICE1, slice2=$NUM_UES_SLICE2, node-role=$NODE_ROLE) ==="
      cd "$UE_DIR" || exit 1
      python3 deploy_multi_ue.py "$NUM_UES_SLICE1" "$NUM_UES_SLICE2" "$NODE_ROLE"
      ;;
    
    *)
      echo "Unknown component: $COMPONENT"
      echo "Valid options: core | slices | cu | ric | ue | kpm | rc | all"
      exit 1
      ;;
  esac
done

echo ""
echo "Deployment of [${COMPONENTS[*]}] completed."
