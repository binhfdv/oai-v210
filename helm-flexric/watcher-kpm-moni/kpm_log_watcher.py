import os
import re
import csv
import json
from datetime import datetime
from kubernetes import client, config, watch

# --- Load in-cluster configuration
config.load_incluster_config()
v1 = client.CoreV1Api()

# --- Default metrics (used if no config is provided)
DEFAULT_METRICS = {
    "UE ID type": r"UE ID type = ([\w-]+)",
    "gnb_cu_ue_f1ap": r"gnb_cu_ue_f1ap = (\d+)",
    "ran_ue_id": r"ran_ue_id = (\d+)",
    "DRB.PdcpSduVolumeDL": r"DRB\.PdcpSduVolumeDL = ([\d.]+)",
    "DRB.PdcpSduVolumeUL": r"DRB\.PdcpSduVolumeUL = ([\d.]+)",
    "DRB.RlcSduDelayDl": r"DRB\.RlcSduDelayDl = ([\d.]+)",
    "DRB.UEThpDl": r"DRB\.UEThpDl = ([\d.]+)",
    "DRB.UEThpUl": r"DRB\.UEThpUl = ([\d.]+)",
    "RRU.PrbTotDl": r"RRU\.PrbTotDl = ([\d.]+)",
    "RRU.PrbTotUl": r"RRU\.PrbTotUl = ([\d.]+)"
}

# --- Load dynamic fields configuration
def load_metrics_config():
    # 1️⃣ Check environment variable
    fields_json = os.getenv("FIELDS_JSON")
    if fields_json:
        print("[INFO] Loading metrics from environment variable FIELDS_JSON")
        return json.loads(fields_json)

    # 2️⃣ Otherwise check file
    config_path = os.getenv("METRICS_CONFIG_PATH", "/config/metrics.json")
    if os.path.exists(config_path):
        print(f"[INFO] Loading metrics from config file: {config_path}")
        with open(config_path, "r") as f:
            return json.load(f)

    print("[WARN] No custom metrics found. Using default metrics.")
    return DEFAULT_METRICS

# --- Compile regex patterns from config
def compile_patterns(metrics):
    return {field: re.compile(pattern) for field, pattern in metrics.items()}

# --- Helpers
def get_csv_filename():
    now = datetime.utcnow()
    return f"/data/oai-kpm-{now.year}-{now.month:02d}-{now.day:02d}-{now.strftime('%H%M%S')}.csv"

def ensure_csv_exists(filepath, fields):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if not os.path.exists(filepath):
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp"] + fields)
            writer.writeheader()

# --- Parse one log line and extract all metrics
def parse_log_line(line, patterns):
    data = {"timestamp": datetime.utcnow().isoformat()}
    for field, pattern in patterns.items():
        match = pattern.search(line)
        if match:
            data[field] = match.group(1)
    return data

# --- Watch logs and stream to CSV
def watch_xapp_logs(namespace="default"):
    metrics = load_metrics_config()
    patterns = compile_patterns(metrics)
    fields = list(metrics.keys())

    print(f"[INFO] Watching xApp pods in namespace '{namespace}'...")
    pods = v1.list_namespaced_pod(namespace)
    xapp_pods = [p.metadata.name for p in pods.items if p.metadata.name.startswith("xapp-kpm-moni-")]

    if not xapp_pods:
        print("[WARN] No matching pods found.")
        return

    csv_path = get_csv_filename()
    ensure_csv_exists(csv_path, fields)

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp"] + fields)
        w = watch.Watch()
        for pod in xapp_pods:
            print(f"[INFO] Streaming logs from pod: {pod}")
            for event in w.stream(v1.read_namespaced_pod_log,
                                  name=pod,
                                  namespace=namespace,
                                  follow=True,
                                  _preload_content=False):
                line = event.decode("utf-8").strip()
                data = parse_log_line(line, patterns)

                # Only write if at least one metric matched
                if len(data) > 1:
                    writer.writerow(data)
                    f.flush()

if __name__ == "__main__":
    ns = os.getenv("WATCH_NAMESPACE", "default")
    watch_xapp_logs(ns)
