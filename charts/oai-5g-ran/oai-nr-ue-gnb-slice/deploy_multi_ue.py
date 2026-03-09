#!/usr/bin/env python3
import os
import sys
import time
import subprocess

# ==============================
# Usage: python3 deploy_multi_ue.py <num_ues_slice1> <num_ues_slice2> <node_role>
# Example: python3 deploy_multi_ue.py 1 1 core
#   - num_ues_slice1: number of UEs assigned to slice1 (dnn=oai1, sd=0x000001)
#   - num_ues_slice2: number of UEs assigned to slice2 (dnn=oai2, sd=0x000005)
#   - node_role: Kubernetes node label value for nodeSelector
# Notes: when you face the issue no IP addresses available in range set: <10.244.0.1-10.244.0.254> from multus
# run this command: sudo rm -rf /var/lib/cni/networks/cbr0
# ==============================

# --- Validate input arguments ---
if len(sys.argv) != 4:
    print("Usage: python3 deploy_multi_ue.py <num_ues_slice1> <num_ues_slice2> <node_role>")
    sys.exit(1)

num_ues_slice1 = int(sys.argv[1])
num_ues_slice2 = int(sys.argv[2])
node_role = sys.argv[3]

# --- Configuration ---
base_ueid = 100           # IMSI suffix starts at 001010000000100
base_telnet_port = 9091   # each UE gets a unique telnet port to avoid conflicts
delay_between_deployments = 10  # seconds

# --- Slice definitions ---
# Add more slices here if needed
slices = [
    {"name": "slice1", "dnn": "oai1",  "sst": "1", "sd": "0x000001", "count": num_ues_slice1},
    {"name": "slice2", "dnn": "oai2",  "sst": "1", "sd": "0x000005", "count": num_ues_slice2},
]

# Shared UE credentials (same key/opc for all UEs)
ue_key = "fec86ba6eb707ed08905757b1bb44b8f"
ue_opc = "C42449363BBAD02B66D16BC975D77CC1"

# --- Helm values template ---
values_template = """kubernetesDistribution: Vanilla

nfimage:
  repository: ddocker122/oai-gnb-slicing
  version: detect
  pullPolicy: IfNotPresent

serviceAccount:
  create: true
  annotations: {{}}
  name: "oai-nr-ue-{sa_number}-sa"

imagePullSecrets:
 - name: "regcred"

config:
  timeZone: "Europe/Paris"
  rfSimServer: "oai-ran"   # service name of the DU (oai-ran / oai-du)
  usrp: "rfsim"

  # --- Slice assignment ---
  fullImsi: "{imsi}"
  fullKey: "{key}"
  opc: "{opc}"
  dnn: "{dnn}"
  sst: "{sst}"
  sd: "{sd}"

  # Telnet port must be unique per UE to avoid port conflicts on the same node
  telnetsrvListenPort: "{telnet_port}"
  telnetsrvHistFile: "~/history.telnetsrv"

  useAdditionalOptions: "--sa -r 106 --numerology 1 --band 78 -C 3619200000 --rfsim"

podSecurityContext:
  runAsUser: 0
  runAsGroup: 0

securityContext:
  privileged: true
  capabilities:
    add:
     - NET_ADMIN
     - NET_RAW
     - SYS_NICE
    drop:
     - ALL

start:
  nrue: true
  tcpdump: false

persistentVolume:
  enabled: true
  claimName: traffic-gen-pvc
  mountPath: /traffic-gen

includeTcpDumpContainer: false

tcpdumpimage:
  repository: docker.io/oaisoftwarealliance/oai-tcpdump-init
  version: alpine-3.20
  pullPolicy: IfNotPresent

debug:
  enabled: true
  image: ddocker122/traffic-gen-sidecar
  version: latest
  pullPolicy: IfNotPresent

resources:
  define: false
  limits:
    nf:
      cpu: 1500m
      memory: 1Gi
    tcpdump:
      cpu: 200m
      memory: 128Mi
  requests:
    nf:
      cpu: 1500m
      memory: 1Gi
    tcpdump:
      cpu: 100m
      memory: 128Mi

terminationGracePeriodSeconds: 0

nodeSelector:
  node-role: {node_role}

nodeName:
"""

# --- Generate Helm values and deploy ---
ue_global_index = 0  # tracks IMSI offset and telnet port across all slices

for sl in slices:
    if sl["count"] == 0:
        continue

    print(f"\n=== Deploying {sl['count']} UE(s) for {sl['name']} "
          f"(dnn={sl['dnn']}, sd={sl['sd']}) ===")

    for i in range(sl["count"]):
        ueid_number = base_ueid + ue_global_index
        imsi = f"001010000000{ueid_number:03d}"
        sa_number = ue_global_index + 1
        telnet_port = base_telnet_port + ue_global_index
        filename = f"generated_values_ue_{sa_number}.yaml"

        # Write YAML file
        with open(filename, "w") as f:
            f.write(values_template.format(
                sa_number=sa_number,
                imsi=imsi,
                key=ue_key,
                opc=ue_opc,
                dnn=sl["dnn"],
                sst=sl["sst"],
                sd=sl["sd"],
                telnet_port=telnet_port,
                node_role=node_role,
            ))

        release_name = f"oai-nr-ue-{sa_number}"
        helm_cmd = ["helm", "install", release_name, ".", "-f", filename]

        print(f"  Deploying UE {sa_number} (IMSI={imsi}, slice={sl['name']}, "
              f"telnet={telnet_port}) on node-role={node_role} ...")
        subprocess.run(helm_cmd)

        ue_global_index += 1

        if not (sl == slices[-1] and i == sl["count"] - 1):
            print(f"  Waiting {delay_between_deployments}s before next deployment...")
            time.sleep(delay_between_deployments)

print("\nAll requested UEs have been deployed successfully!")
