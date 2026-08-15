"""
Extract prediction accuracy from agent log files.

Reads logs_cnn_{T}.txt / logs_cnn_agent_{T}.txt  → accuracy_cnn.csv
Reads logs_xg_{T}.txt  / logs_xg_agent_{T}.txt   → accuracy_xg.csv

Output columns: T, normal, agent  (ratio, 4 decimal places)
"""
import re
import csv
from pathlib import Path

LOGS_DIR = Path(__file__).parent / "logs"
T_VALUES = [4, 8, 16, 32]

PRED_RE = re.compile(r"Predicted class:\s*(\w+)")

MODELS = [
    {
        "name":        "cnn",
        "normal_pat":  "logs_cnn_{T}.txt",
        "agent_pat":   "logs_cnn_agent_{T}.txt",
        "ground_truth": "URLLC",
        "output":      "accuracy_cnn.csv",
    },
    {
        "name":        "xg",
        "normal_pat":  "logs_xg_{T}.txt",
        "agent_pat":   "logs_xg_agent_{T}.txt",
        "ground_truth": "eMBB",
        "output":      "accuracy_xg.csv",
    },
]


def compute_accuracy(log_path: Path, ground_truth: str) -> float | None:
    if not log_path.exists():
        print(f"  [MISSING] {log_path.name}")
        return None
    predictions = PRED_RE.findall(log_path.read_text())
    total = len(predictions)
    if total == 0:
        print(f"  [NO PREDICTIONS] {log_path.name}")
        return None
    correct = sum(1 for p in predictions if p == ground_truth)
    acc = correct / total
    print(f"  {log_path.name:<35}  {correct}/{total}  = {acc:.4f}")
    return acc


for model in MODELS:
    print(f"\n=== {model['name'].upper()} (ground truth: {model['ground_truth']}) ===")
    rows = []
    for T in T_VALUES:
        normal_path = LOGS_DIR / model["normal_pat"].replace("{T}", str(T))
        agent_path  = LOGS_DIR / model["agent_pat"].replace("{T}", str(T))
        acc_normal  = compute_accuracy(normal_path, model["ground_truth"])
        acc_agent   = compute_accuracy(agent_path,  model["ground_truth"])
        rows.append({
            "T":      T,
            "normal": f"{acc_normal:.4f}" if acc_normal is not None else "N/A",
            "agent":  f"{acc_agent:.4f}"  if acc_agent  is not None else "N/A",
        })

    out_path = LOGS_DIR / model["output"]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["T", "normal", "agent"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → {out_path}")
