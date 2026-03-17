#!/bin/bash

# ==============================
# OAI Basic Deployment Script
# Usage: ./deploy_oai.sh <repodir> [--c] [components...]
# Components: core | cu | gnb | ric | ue | ue-gnb | kpm | gmrp | rc | xchain-basic | ping | all
# Options:
#   --c    Continue deployment (skip helm uninstall)
# Config (env vars, defaults shown):
#   PING_TARGET=10.1.2.14   target IP for UE ping test
# Example:
#   ./deploy_oai.sh /home/lapdk/workspace/oai-v210 core cu ric
#   ./deploy_oai.sh /home/lapdk/workspace/oai-v210 all
#   ./deploy_oai.sh /home/lapdk/workspace/oai-v210 --c kpm

# # Deploy step by step
# ./deploy_oai.sh /home/lapdk/workspace/oai-v210 core
# ./deploy_oai.sh /home/lapdk/workspace/oai-v210 --c cu
# ./deploy_oai.sh /home/lapdk/workspace/oai-v210 --c ric

# Key points:
# all expands to core cu ric in that order
# --c skips uninstall (continue/add components to existing deployment)
# ping runs a connectivity test from every UE pod via oaitun_ue1
# ==============================

# --- Validate input ---
if [ -z "$1" ]; then
  echo "Usage: $0 <repodir> [--c] [components...]"
  echo "Components: core | cu | gnb | ric | ue | ue-gnb | kpm | gmrp | rc | xchain-basic | ping | all"
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
    COMPONENTS=(core cu)
  else
    COMPONENTS+=("$arg")
  fi
done

if [ ${#COMPONENTS[@]} -eq 0 ]; then
  echo "Error: No components specified."
  echo "Valid options: core | cu | gnb | ric | ue | ue-gnb | kpm | gmrp | rc | xchain-basic | ping | all"
  exit 1
fi

# --- Config (override via env vars) ---
PING_TARGET="${PING_TARGET:-10.1.2.14}" # dn ip

# --- Helper: ping test for all UE pods ---
ping_test() {
  echo ""
  echo "=== Ping test for all UEs (target: $PING_TARGET) ==="
  PODS=$(kubectl get pods -n oai -l app.kubernetes.io/name=oai-nr-ue \
    -o jsonpath="{.items[*].metadata.name}" 2>/dev/null)

  if [ -z "$PODS" ]; then
    echo "No UE pods found."
    return
  fi

  PASS=0
  FAIL=0
  for POD in $PODS; do
    INSTANCE=$(kubectl get pod "$POD" -n oai \
      -o jsonpath="{.metadata.labels.app\.kubernetes\.io/instance}" 2>/dev/null)
    echo -n "  [$INSTANCE / $POD] ping $PING_TARGET via oaitun_ue1 ... "
    if kubectl exec -n oai "$POD" -c nr-ue -- \
        ping "$PING_TARGET" -I oaitun_ue1 -c 2 -W 3 -q 2>/dev/null | \
        grep -q "2 received"; then
      echo "OK"
      PASS=$((PASS + 1))
    else
      echo "FAIL"
      FAIL=$((FAIL + 1))
    fi
  done
  echo "  Result: $PASS passed, $FAIL failed"
}

# --- Helper: wait for near-RT RIC to have all RAN components connected ---
wait_for_ric_healthy() {
  local TIMEOUT=300
  local INTERVAL=10
  local ELAPSED=0
  local RAN_COMPONENTS=("ngran_gNB_DU" "ngran_gNB_CUUP" "ngran_gNB_CUCP")

  echo ""
  echo "=== Waiting for near-RT RIC: all RAN components connected ==="

  while true; do
    RIC_POD=$(kubectl get pods -n oai -l app=oai-nearrt-ric \
      --no-headers -o custom-columns=":metadata.name,:status.phase" 2>/dev/null | head -1)
    RIC_NAME=$(echo "$RIC_POD" | awk '{print $1}')
    RIC_PHASE=$(echo "$RIC_POD" | awk '{print $2}')

    if [ -z "$RIC_NAME" ]; then
      echo "  No RIC pod found, waiting..."
    else
      WAIT_REASON=$(kubectl get pod "$RIC_NAME" -n oai \
        -o jsonpath="{.status.containerStatuses[0].state.waiting.reason}" 2>/dev/null)
      if [ "$RIC_PHASE" = "Failed" ] || [ "$WAIT_REASON" = "CrashLoopBackOff" ] || [ "$WAIT_REASON" = "Error" ]; then
        echo "  RIC pod $RIC_NAME is in ${RIC_PHASE}/${WAIT_REASON}. Deleting for clean restart..."
        kubectl delete pod "$RIC_NAME" -n oai --wait=false 2>/dev/null
        sleep 10
        ELAPSED=0
        continue
      fi

      LOGS=$(kubectl logs "$RIC_NAME" -n oai 2>/dev/null)
      ALL_CONNECTED=true
      for RAN_TYPE in "${RAN_COMPONENTS[@]}"; do
        if ! echo "$LOGS" | grep -q "E2 SETUP-REQUEST rx.*$RAN_TYPE"; then
          ALL_CONNECTED=false
          break
        fi
      done

      if $ALL_CONNECTED; then
        echo "  RIC pod $RIC_NAME is healthy — DU, CU-UP, CU-CP all connected."
        return
      else
        echo "  RIC pod $RIC_NAME running but not all RAN components connected yet..."
      fi
    fi

    if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
      echo "  Timeout waiting for RIC health. Deleting pod for clean restart..."
      kubectl delete pod "$RIC_NAME" -n oai --wait=false 2>/dev/null
      ELAPSED=0
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
  done
}

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
      echo "=== Deploying 5G Core ==="
      cd "$REPODIR/charts/oai-5g-core/oai-5g-basic" || exit 1
      helm dependency update
      helm install oai-5g-basic . -n oai
      wait_for_pod_ready oai-amf AMF
      ;;

    cu)
      echo ""
      echo "=== Deploying CU-CP ==="
      cd "$REPODIR/charts/oai-5g-ran/oai-cu-cp" || exit 1
      helm install oai-cu-cp . -n oai
      wait_for_pod_ready oai-cu-cp CU-CP

      echo "=== Deploying CU-UP ==="
      cd "$REPODIR/charts/oai-5g-ran/oai-cu-up" || exit 1
      helm install oai-cu-up . -n oai
      wait_for_pod_ready oai-cu-up CU-UP

      echo "=== Deploying DU ==="
      cd "$REPODIR/charts/oai-5g-ran/oai-du" || exit 1
      helm install oai-du . -n oai
      wait_for_pod_ready oai-du DU
      ;;

    gnb)
      echo ""
      echo "=== Deploying gNB (e2-gnb) ==="
      cd "$REPODIR/helm-flexric" || exit 1
      helm install e2-gnb ./e2-gnb -n oai
      sleep 7
      ;;

    ue)
      echo ""
      echo "=== Deploying oai-nr-ue ==="
      cd "$REPODIR/charts/oai-5g-ran/oai-nr-ue" || exit 1
      helm install oai-nr-ue . -n oai
      sleep 30
      ping_test
      ;;

    ue-gnb)
      echo ""
      echo "=== Deploying oai-nr-ue-gnb ==="
      cd "$REPODIR/charts/oai-5g-ran/oai-nr-ue-gnb" || exit 1
      helm install oai-nr-ue-gnb . -n oai
      sleep 30
      ping_test
      ;;

    ric)
      echo ""
      echo "=== Deploying near-RT RIC ==="
      cd "$REPODIR/helm-flexric/nearrt-ric" || exit 1
      helm dependency update
      helm install near-rt-ric . -n oai
      wait_for_pod_ready oai-nearrt-ric near-RT-RIC
      ;;

    kpm)
      echo ""
      echo "=== Deploying xApp: KPM monitor ==="
      wait_for_ric_healthy
      cd "$REPODIR/helm-flexric/xapp-kpm-moni" || exit 1
      helm install xapp-kpm-moni . -n oai
      sleep 7
      ;;

    gmrp)
      echo ""
      echo "=== Deploying xApp: GTP-MAC-RLC-PDCP monitor ==="
      cd "$REPODIR/helm-flexric/xapp-gtp-mac-rlc-pdcp-moni" || exit 1
      helm install xapp-gtp-mac-rlc-pdcp-moni . -n oai
      sleep 7
      ;;

    rc)
      echo ""
      echo "=== Deploying xApp: RC monitor ==="
      cd "$REPODIR/helm-flexric/xapp-rc-moni" || exit 1
      helm install xapp-rc-moni . -n oai
      sleep 7
      ;;

    xchain-basic)
      echo ""
      echo "=== Deploying xchain-basic ==="
      cd "$REPODIR/xChain/helm-charts/xchain-basic" || exit 1
      helm dependency update
      helm install xchain-basic . -n oai
      ;;

    ping)
      ping_test
      ;;

    *)
      echo "Unknown component: $COMPONENT"
      echo "Valid options: core | cu | gnb | ric | ue | ue-gnb | kpm | gmrp | rc | xchain-basic | ping | all"
      exit 1
      ;;
  esac
done

echo ""
echo "Deployment of [${COMPONENTS[*]}] completed."
