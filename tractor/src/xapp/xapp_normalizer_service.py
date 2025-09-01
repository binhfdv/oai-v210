from flask import Flask, request, jsonify
import pickle, numpy as np
from python.visual_xapp_inference import process_norm_params

app = Flask(__name__)

colsparams = None
indexes_to_keep = None
map_feat2KPI = None
num_feats = None
slice_len = None

@app.route("/load_norm", methods=["POST"])
def load_norm():
    global colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len
    norm_param_path = request.json["norm_param_path"]

    if not norm_param_path:
        return {"error": "norm_param_path is required"}, 400

    all_feats_raw = int(request.json.get("all_feats_raw", 31))
    colsparam_dict = pickle.load(open(norm_param_path, "rb"))
    colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len, _ = process_norm_params(all_feats_raw, colsparam_dict)
    # print("Loaded normalization parameters", colsparams, indexes_to_keep, map_feat2KPI, num_feats, slice_len)
    return jsonify({"status": "ok", "num_feats": int(num_feats), "slice_len": int(slice_len)})

@app.route("/normalize", methods=["POST"])
def normalize():
    global colsparams, indexes_to_keep
    kpi = np.array(request.json["kpi"], dtype=float)
    kpi_filt = kpi[indexes_to_keep]
    # normalize -> single vector (num_feats,)
    for f in range(kpi_filt.shape[0]):
        mn, mx = colsparams[f]['min'], colsparams[f]['max']
        if kpi_filt[f] < mn: kpi_filt[f] = mn
        if kpi_filt[f] > mx: kpi_filt[f] = mx
        kpi_filt[f] = (kpi_filt[f] - mn) / (mx - mn)
    return jsonify({"normalized": kpi_filt.tolist()})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
