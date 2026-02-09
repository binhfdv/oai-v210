from flask import Flask, request, jsonify

app = Flask(__name__)
buffers = {}  # stream_id -> list of vectors

@app.route("/reset", methods=["POST"])
def reset():
    stream = request.json.get("stream", "default")
    buffers[stream] = []
    return jsonify({"status": "reset", "stream": stream})

@app.route("/update", methods=["POST"])
def update():
    stream = request.json.get("stream", "default")
    kpi = request.json["kpi"]  # normalized vector [num_feats]
    slice_len = int(request.json["slice_len"])
    num_feats = int(request.json["num_feats"])

    buf = buffers.setdefault(stream, [])
    buf.append(kpi)
    if len(buf) > slice_len:
        buf.pop(0)

    ready = len(buf) == slice_len
    return jsonify({"ready": ready, "window": buf if ready else []})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)
