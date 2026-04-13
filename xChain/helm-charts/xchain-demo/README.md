# xChain Netsoft 2026 Demo — Deployment Guide

Single-machine deployment (all components on one node).

## Prerequisites

- Kubernetes cluster running (`kubectl get nodes` shows Ready)
- Docker images built and pushed:
  - `ddocker122/xchain-gui-server:latest`
  - `ddocker122/universal-agent:latest`
  - `ddocker122/xchain-smartgw-demo:latest`
  - `ddocker122/tractor-xapp-mono:latest`
  - `ddocker122/xchain-fastinfer:latest`
- Node labeled: `kubectl label node <node-name> node-role=core`
- Results folder exists on the node:
  ```
  xChain/src/2026-netsoft-demo/api/server/demo/data/{vr,haptic,social,iot}/
  ```

---

## Deployment Steps

### Step 1 — Deploy 5G Core, RAN, RIC, and xChain demo

From the repo root:

```bash
./deploy_oai.sh /home/lapdk/workspace/oai-v210 core ric cu ue-gnb kpm kpm-tools xchain-demo
```

This deploys in order:
1. **5G Core** (AMF, SMF, UPF, etc.) + oai-traffic-server (with universal-agent sidecar)
2. **near-RT RIC**
3. **CU-CP, CU-UP, DU**
4. **UE + gNB** (1 UE by default)
5. **KPM xApp**
6. **KPM tools** (watcher + cleaner — waits for KPM xApp to be ready first)
7. **xchain-demo umbrella** (gui-server, smartgw-demo, fastinfer, tractor-mono, tractor-kpm-oai)

---

## Verify Deployment

```bash
kubectl get pods -n oai
```

Expected pods:
| Pod | Ready |
|-----|-------|
| oai-amf, oai-smf, oai-upf, ... | 1/1 |
| oai-traffic-server | 3/3 (iperf3 + debug + agent) |
| oai-nearrt-ric | 1/1 |
| oai-cu-cp, oai-cu-up, oai-du | 1/1 |
| oai-nr-ue-1 | 2/2 |
| xapp-kpm-moni | 1/1 |
| xchain-gui-server | 1/1 |
| xchain-smartgw-demo | 2/2 (smartgw + agent) |
| xchain-fastinfer | 2/2 (model + log-collector) |
| tractor-mono | 2/2 (model + log-collector) |
| tractor-kpm-oai | 1/1 |
| watcher-kpm-moni | 1/1 |
| cleaner-kpm-moni | 1/1 |

---

## Access the GUI

Open in browser: **http://lapdk:30500**
```bash
lapdk: change this with the name of your host or the its IP.
```
---

## Run the Demo

1. Select a traffic type: **VR / Haptic / Social / IoT**
2. Select models: **FastInfer** and/or **CNN**
3. Click **START**
4. Watch live latency and accuracy charts update

---

## Teardown

```bash
helm uninstall watcher-kpm-moni cleaner-kpm-moni
helm uninstall xchain-demo -n oai
helm uninstall $(helm list -aq -n oai) -n oai
```

## Distributed

NAME   STATUS   ROLES           AGE     VERSION
core   Ready    control-plane   24m     v1.30.5
pi     Ready    <none>          7m4s    v1.30.5
ran    Ready    <none>          8m27s   v1.30.5

# On core node:
sudo apt install -y nfs-kernel-server

# Export the results folder, change with the real path in node
echo "/home/core/oai-v210/xChain/src/2026-netsoft-demo/api/server/demo/data *(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports

sudo exportfs -a
sudo systemctl enable --now nfs-kernel-server

# On ran and pi nodes:
sudo apt install -y nfs-common

# On ran and pi, to test NFS is reachable from ran and pi::
showmount -e <core-node-ip>
showmount -e 192.168.21.153