import os
import json
import subprocess

namespace = 'oai'
ip_address = "10.244.0.1"
network = "cni0"

# Get full pod JSON
pod_name_cmd = [
    "kubectl", "get", "pods", "-n", namespace,
    "-l", "app.kubernetes.io/name=oai-amf",
    "-o", "jsonpath={.items[0].metadata.name}"
]
pod_name = subprocess.check_output(pod_name_cmd).decode().strip()

pod_json_cmd = ["kubectl", "get", "pod", pod_name, "-n", namespace, "-o", "json"]
pod_json = subprocess.check_output(pod_json_cmd)
pod_data = json.loads(pod_json)

# Default to .status.podIP
amf_ip = pod_data["status"]["podIP"]

# Try to get n2 IP from annotation
annotations = pod_data["metadata"].get("annotations", {})
network_status_json = annotations.get("k8s.v1.cni.cncf.io/network-status", "")

try:
    network_status = json.loads(network_status_json)
    for net in network_status:
        if net.get("interface") == "n2" and "ips" in net:
            amf_ip = net["ips"][0]
            break
except Exception as e:
    print("Warning: Could not parse network-status annotation:", e)

# Set up virtual interface
os.system(f"sudo ifconfig {network}:1 {ip_address} up")

# Update OAI-gnb.yaml
with open('OAI-gnb.yaml', 'r') as file:
    data = file.read()
data = data.replace("xxx", ip_address)
data = data.replace("yyy", amf_ip)
with open('build/OAI-gnb.yaml', 'w') as file:
    file.write(data)

# Update OAI-ue.yaml
with open('OAI-ue.yaml', 'r') as file:
    data = file.read()
data = data.replace("xxx", ip_address)
data = data.replace("yyy", namespace)
with open('build/OAI-ue.yaml', 'w') as file:
    file.write(data)

print(f"UERANSIM files configuration updated with AMF IP: {amf_ip}")
