#!/usr/bin/env python3
"""
xChain Orchestrator
- Chain registry: register / remove / list xApp chains
- Routing table:  map traffic class -> chain
- Flask REST API for provisioning and configuration of xApp chains
"""
import os
import logging
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

# chain registry: name -> {host, port}
chains = {
    "tractor":   {"host": TRACTOR_HOST,   "port": TRACTOR_PORT},
    "fastinfer": {"host": FASTINFER_HOST, "port": FASTINFER_PORT},
}

# routing table: traffic_class -> chain_name
routing = {
    "eMBB-mMTC":  "tractor",
    "eMBB":       "fastinfer",
    "mMTC":       "fastinfer",
    "URLLC-mMTC": "fastinfer",
    "URLLC-eMBB": "fastinfer",
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
    return jsonify({"chains": status})


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

PORT = int(os.getenv("PORT", "5010"))

if __name__ == "__main__":
    logging.info(f"[xChain Orchestrator] Starting on port {PORT}")
    logging.info(f"[xChain Orchestrator] Chains:  {chains}")
    logging.info(f"[xChain Orchestrator] Routing: {routing}")
    app.run(host="0.0.0.0", port=PORT)
