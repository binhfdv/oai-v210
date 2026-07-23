#!/usr/bin/env python3
"""
xChain Orchestrator
- Chain registry: register / remove / list xApp chains
- Routing table:  map traffic class -> chain
- Flask REST API for provisioning and configuration of xApp chains
- Journal extension: push operator context to filtering agent on startup
"""
import os
import time
import logging
import threading
import requests
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)

# ---------------------------------------------------------
# Pre-loaded chains from environment
# ---------------------------------------------------------
TRACTOR_HOST    = os.getenv("TRACTOR_HOST",    "tractor-orchestrator")
TRACTOR_PORT    = int(os.getenv("TRACTOR_PORT",    "4300"))
FASTINFER_HOST  = os.getenv("FASTINFER_HOST",  "xchain-fastinfer")
FASTINFER_PORT  = int(os.getenv("FASTINFER_PORT",  "4400"))

# Journal extension: preprocessing agent (sidecar TCP port on tractor-mono)
PREPROC_AGENT_HOST = os.getenv("PREPROC_AGENT_HOST", "")
PREPROC_AGENT_PORT = int(os.getenv("PREPROC_AGENT_PORT", "4301"))   # TCP data port
PREPROC_AGENT_HTTP = int(os.getenv("PREPROC_AGENT_HTTP", "5100"))   # HTTP port (complaint)

# Journal extension: filtering agent (sidecar HTTP port on xchain-unicorn)
FILTER_AGENT_HOST  = os.getenv("FILTER_AGENT_HOST",  "")
FILTER_AGENT_PORT  = int(os.getenv("FILTER_AGENT_PORT",  "5101"))

# Operator-configured overlap context — pushed to filtering agent on startup
CONTEXT_LABEL = os.getenv("CONTEXT_LABEL", "")

# chain registry: name -> {host, port}
chains = {
    "tractor":   {"host": TRACTOR_HOST,   "port": TRACTOR_PORT},
    "fastinfer": {"host": FASTINFER_HOST, "port": FASTINFER_PORT},
}

# Register preprocessing agent as its own chain if configured
# (SmartGW will connect to this TCP port to route URLLC-overlap traffic)
if PREPROC_AGENT_HOST:
    chains["tractor-agent"] = {"host": PREPROC_AGENT_HOST, "port": PREPROC_AGENT_PORT}

# routing table: traffic_class -> chain_name
routing = {
    "eMBB-mMTC":  "tractor",
    "eMBB":       "fastinfer",
    "mMTC":       "fastinfer",
    "URLLC-mMTC": "fastinfer" if not PREPROC_AGENT_HOST else "tractor-agent",
    "URLLC-eMBB": "fastinfer" if not PREPROC_AGENT_HOST else "tractor-agent",
    "UNKNOWN":    "fastinfer",
}


# ---------------------------------------------------------
# Chain registry endpoints
# ---------------------------------------------------------

@app.route("/chains", methods=["GET"])
def get_chains():
    return jsonify(chains)


@app.route("/chains", methods=["POST"])
def add_chain():
    data = request.get_json()
    name = data.get("name")
    host = data.get("host")
    port = data.get("port")

    if not name or not host or not port:
        return jsonify({"error": "name, host, port required"}), 400

    chains[name] = {"host": host, "port": int(port)}
    logging.info(f"[Registry] Chain added: {name} -> {host}:{port}")
    return jsonify({"status": "added", "chain": chains[name]}), 201


@app.route("/chains/<name>", methods=["DELETE"])
def remove_chain(name):
    if name not in chains:
        return jsonify({"error": f"Chain '{name}' not found"}), 404

    used_by = [cls for cls, c in routing.items() if c == name]
    if used_by:
        return jsonify({
            "error": f"Chain '{name}' is used by routing rules: {used_by}. Update routing first."
        }), 409

    del chains[name]
    logging.info(f"[Registry] Chain removed: {name}")
    return jsonify({"status": "removed"}), 200


# ---------------------------------------------------------
# Routing table endpoints
# ---------------------------------------------------------

@app.route("/routing", methods=["GET"])
def get_routing():
    resolved = {}
    for cls, chain_name in routing.items():
        chain = chains.get(chain_name)
        if chain:
            resolved[cls] = {"chain": chain_name, "host": chain["host"], "port": chain["port"]}
        else:
            resolved[cls] = {"chain": chain_name, "error": "chain not registered"}
    return jsonify(resolved)


@app.route("/routing", methods=["PUT"])
def update_routing():
    data = request.get_json()
    errors = {}
    for cls, chain_name in data.items():
        if chain_name not in chains:
            errors[cls] = f"Chain '{chain_name}' not registered"
    if errors:
        return jsonify({"error": "Unknown chains", "details": errors}), 400

    routing.update(data)
    logging.info(f"[Routing] Updated: {data}")
    return jsonify({"status": "updated", "routing": routing})


# ---------------------------------------------------------
# Journal: context management
# ---------------------------------------------------------

@app.route("/context", methods=["GET"])
def get_context():
    return jsonify({"context_label": CONTEXT_LABEL,
                    "filter_agent":  f"{FILTER_AGENT_HOST}:{FILTER_AGENT_PORT}"})


@app.route("/context", methods=["PUT"])
def update_context():
    global CONTEXT_LABEL
    data = request.get_json() or {}
    CONTEXT_LABEL = data.get("context_label", CONTEXT_LABEL)
    logging.info(f"[Context] Updated: {CONTEXT_LABEL}")
    _push_context_to_filter_agent(CONTEXT_LABEL)
    return jsonify({"status": "ok", "context_label": CONTEXT_LABEL})


def _push_context_to_filter_agent(ctx_label):
    if not FILTER_AGENT_HOST or not ctx_label:
        return
    try:
        requests.post(
            f"http://{FILTER_AGENT_HOST}:{FILTER_AGENT_PORT}/context",
            json={"context_label": ctx_label},
            timeout=5,
        )
        logging.info(f"[Context] Pushed '{ctx_label}' to filtering agent at "
                     f"{FILTER_AGENT_HOST}:{FILTER_AGENT_PORT}")
    except Exception as e:
        logging.warning(f"[Context] Push to filtering agent failed: {e}")


def _startup_push_context():
    """Retry pushing context to filtering agent until it responds."""
    if not FILTER_AGENT_HOST or not CONTEXT_LABEL:
        return
    for attempt in range(1, 11):
        try:
            requests.post(
                f"http://{FILTER_AGENT_HOST}:{FILTER_AGENT_PORT}/context",
                json={"context_label": CONTEXT_LABEL},
                timeout=5,
            )
            logging.info(f"[Context] Startup push '{CONTEXT_LABEL}' succeeded "
                         f"(attempt {attempt})")
            return
        except Exception as e:
            logging.warning(f"[Context] Startup push attempt {attempt} failed: {e}")
            time.sleep(5)
    logging.error("[Context] Startup push exhausted retries")


# ---------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    status = {}
    for name, chain in chains.items():
        try:
            r = requests.get(
                f"http://{chain['host']}:{chain['port']}/health", timeout=2
            )
            status[name] = "ok" if r.status_code == 200 else f"http {r.status_code}"
        except Exception as e:
            status[name] = f"unreachable ({e})"
    return jsonify({"chains": status,
                    "context_label": CONTEXT_LABEL,
                    "filter_agent":  f"{FILTER_AGENT_HOST}:{FILTER_AGENT_PORT}"})


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

PORT = int(os.getenv("PORT", "5010"))

if __name__ == "__main__":
    logging.info(f"[xChain Orchestrator] Starting on port {PORT}")
    logging.info(f"[xChain Orchestrator] Chains:  {chains}")
    logging.info(f"[xChain Orchestrator] Routing: {routing}")
    logging.info(f"[xChain Orchestrator] Context: {CONTEXT_LABEL!r}  "
                 f"filter-agent={FILTER_AGENT_HOST}:{FILTER_AGENT_PORT}")
    if FILTER_AGENT_HOST and CONTEXT_LABEL:
        threading.Thread(target=_startup_push_context, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
