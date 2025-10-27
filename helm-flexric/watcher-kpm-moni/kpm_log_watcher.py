import os
import re
import csv
import json
import logging
from datetime import datetime
from kubernetes import client, config, watch

# --- Configure logging ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "DEBUG").upper(),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# --- Load in-cluster configuration ---
try:
    config.load_incluster_config()
    logger.info("Loaded in-cluster Kubernetes configuration.")
except Exception as e:
    logger.warning(f"Failed to load in-cluster config: {e}. Trying local kubeconfig...")
    try:
        config.load_kube_config()
        logger.info("Loaded local kubeconfig for debugging.")
    except Exception as e2:
        logger.error(f"Failed to load any Kubernetes config: {e2}")
        raise

v1 = client.CoreV1Api()

# --- Default metrics ---
DEFAULT_METRICS = {
    "UE ID type": r"UE ID type = ([\w-]+)",
    "gnb_cu_cp_ue_e1ap": r"gnb_cu_cp_ue_e1ap = (\d+)",
    "gnb_cu_ue_f1ap": r"gnb_cu_ue_f1ap = (\d+)",
    "ran_ue_id": r"ran_ue_id = (\d+)",
    "DRB.PdcpSduVolumeDL": r"DRB\.PdcpSduVolumeDL = ([\d.]+) \[kb\]",
    "DRB.PdcpSduVolumeUL": r"DRB\.PdcpSduVolumeUL = ([\d.]+) \[kb\]",
    "DRB.RlcSduDelayDl": r"DRB\.RlcSduDelayDl = ([\d.]+) \[μs\]",
    "DRB.UEThpDl": r"DRB\.UEThpDl = ([\d.]+) \[kbps\]",
    "DRB.UEThpUl": r"DRB\.UEThpUl = ([\d.]+) \[kbps\]",
    "RRU.PrbTotDl": r"RRU\.PrbTotDl = ([\d.]+) \[PRBs\]",
    "RRU.PrbTotUl": r"RRU\.PrbTotUl = ([\d.]+) \[PRBs\]"
}

# --- Load dynamic fields configuration ---
def load_metrics_config():
    fields_json = os.getenv("FIELDS_JSON")
    if fields_json:
        logger.info("Loading metrics from environment variable FIELDS_JSON.")
        return json.loads(fields_json)

    config_path = os.getenv("METRICS_CONFIG_PATH", "/config/metrics.json")
    if os.path.exists(config_path):
        logger.info(f"Loading metrics from config file: {config_path}")
        with open(config_path, "r") as f:
            return json.load(f)

    logger.warning("No custom metrics found. Using default metrics.")
    return DEFAULT_METRICS

# --- Compile regex patterns from config ---
def compile_patterns(metrics):
    compiled = {field: re.compile(pattern) for field, pattern in metrics.items()}
    logger.debug(f"Compiled {len(compiled)} metric patterns.")
    return compiled

# --- Helpers ---
def get_csv_filename():
    now = datetime.utcnow()
    filename = f"/data/raw/oai-kpm-{now.year}-{now.month:02d}-{now.day:02d}-{now.strftime('%H%M%S')}.csv"
    logger.info(f"CSV output path: {filename}")
    return filename

def ensure_csv_exists(filepath, fields):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if not os.path.exists(filepath):
        logger.info(f"Creating new CSV file: {filepath}")
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp"] + fields)
            writer.writeheader()
    else:
        logger.debug(f"Appending to existing CSV: {filepath}")

# --- Watch logs and stream to CSV ---
def watch_xapp_logs(namespace="default"):
    metrics = load_metrics_config()
    patterns = compile_patterns(metrics)
    fields = list(metrics.keys())

    logger.info(f"Watching xApp pods in namespace '{namespace}'...")
    pods = v1.list_namespaced_pod(namespace)
    xapp_pods = [p.metadata.name for p in pods.items if p.metadata.name.startswith("xapp-kpm-moni-")]

    if not xapp_pods:
        logger.warning("No matching pods found.")
        return

    csv_path = get_csv_filename()
    ensure_csv_exists(csv_path, fields)

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp"] + fields)
        w = watch.Watch()

        for pod in xapp_pods:
            logger.info(f"Streaming logs from pod: {pod}")
            try:
                current_ue = None
                buffer = {}

                for event in w.stream(
                    v1.read_namespaced_pod_log,
                    name=pod,
                    namespace=namespace,
                    follow=True,
                    _preload_content=False
                ):
                    if isinstance(event, bytes):
                        line = event.decode("utf-8").strip()
                    else:
                        line = str(event).strip()

                    if not line:
                        continue

                    logger.debug(f"Line received: {line}")

                    # Detect start of a new UE by gnb_cu_ue_f1ap or gnb_cu_cp_ue_e1ap
                    ue_match = None
                    for ue_field in ["gnb_cu_ue_f1ap", "gnb_cu_cp_ue_e1ap"]:
                        match = patterns.get(ue_field).search(line)
                        if match:
                            ue_id = match.group(1)
                            ue_match = (ue_field, ue_id)
                            break

                    if ue_match:
                        # Flush previous UE buffer
                        if current_ue and buffer:
                            buffer["timestamp"] = datetime.utcnow().isoformat()
                            writer.writerow(buffer)
                            f.flush()
                            logger.debug(f"Flushed metrics for UE {current_ue}: {buffer}")
                        # Start new UE buffer
                        current_ue = ue_match[1]
                        buffer = {ue_match[0]: current_ue}
                        logger.debug(f"Detected new UE {current_ue}, starting buffer")

                        # Also check if "UE ID type" is on the same line
                        type_match = patterns.get("UE ID type").search(line)
                        if type_match:
                            buffer["UE ID type"] = type_match.group(1)
                            logger.debug(f"Captured UE ID type={buffer['UE ID type']} for UE {current_ue}")
                        continue

                    # Add other metric lines to current UE buffer
                    if current_ue:
                        matched_any = False
                        for field, pattern in patterns.items():
                            if field in ["gnb_cu_ue_f1ap", "gnb_cu_cp_ue_e1ap", "UE ID type"]:
                                continue
                            m = pattern.search(line)
                            if m:
                                buffer[field] = m.group(1)
                                matched_any = True
                                logger.debug(f"Matched {field}={m.group(1)} for UE {current_ue}")
                        if not matched_any:
                            logger.debug("No pattern matched this line.")
                    else:
                        logger.debug("No current UE buffer, skipping line.")

                    # Detect end of KPM block
                    if "KPM ind_msg latency" in line:
                        # Flush previous UE buffer at start of new KPM block
                        if current_ue and buffer:
                            buffer["timestamp"] = datetime.utcnow().isoformat()
                            writer.writerow(buffer)
                            f.flush()
                            logger.debug(f"Flushed metrics for UE {current_ue} at new KPM block: {buffer}")
                        current_ue = None
                        buffer = {}

            except Exception as e:
                logger.exception(f"Error streaming logs from {pod}: {e}")

if __name__ == "__main__":
    ns = os.getenv("WATCH_NAMESPACE", "default")
    logger.info(f"Starting KPM log watcher in namespace: {ns}")
    watch_xapp_logs(ns)
