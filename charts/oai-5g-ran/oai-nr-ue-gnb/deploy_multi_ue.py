#!/usr/bin/env python3
import os
import sys
import time
import subprocess

# ==============================
# Usage: python3 deploy_multi_ue.py <num_ues> <node_role>
# Example: python3 deploy_multi_ue.py 20 core
# Or: ./deploy_multi_ue.py 20 core
# Notes: when you face the issue no IP addresses available in range set: <10.244.0.1-10.244.0.254> from multus
# run this command: sudo rm -rf /var/lib/cni/networks/cbr0
# ==============================

# --- Validate input arguments ---
if len(sys.argv) != 3:
    print("Usage: python3 deploy_multi_ue.py <num_ues> <node_role>")
    sys.exit(1)

num_ues = int(sys.argv[1])
node_role = sys.argv[2]

# --- Configuration ---
base_ueid = 100  # starting from 001010000000100
delay_between_deployments = 10  # seconds

# --- Helm values template ---
values_template = """kubernetesDistribution: Vanilla

nfimage:
  repository: ddocker122/oai-e2gnb-mono
  version: dev
  pullPolicy: IfNotPresent

serviceAccount:
  create: true
  annotations: {{}}
  name: "oai-nr-ue-{sa_number}-sa"

imagePullSecrets:
 - name: "regcred"

config:
  timeZone: "Europe/Paris"
  rfSimServer: "oai-ran"
  usrp: "rfsim"
  useAdditionalOptions: "--band 78 -C 3619200000 -r 106 --numerology 1 --ssb 516 -E --rfsim --uicc0.imsi {imsi}"

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

includeTcpDumpContainer: false

tcpdumpimage:
  repository: docker.io/oaisoftwarealliance/oai-tcpdump-init
  version: alpine-3.20
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
for i in range(num_ues):
    ueid_number = base_ueid + i
    imsi = f"001010000000{ueid_number:03d}"
    sa_number = i + 1  # UE count starts at 1
    filename = f"generated_values_ue_{sa_number}.yaml"

    # Write YAML file
    with open(filename, "w") as f:
        f.write(values_template.format(sa_number=sa_number, imsi=imsi, node_role=node_role))

    # Helm release name
    release_name = f"oai-nr-ue-{sa_number}"
    helm_cmd = ["helm", "install", release_name, ".", "-f", filename]

    print(f"Deploying UE {sa_number} (IMSI={imsi}) on node-role={node_role} ...")
    subprocess.run(helm_cmd)

    if i < num_ues - 1:
        print(f"Waiting {delay_between_deployments}s before next deployment...")
        time.sleep(delay_between_deployments)

print("\nAll requested UEs have been deployed successfully!")
