"""
Parse inference logs and generate accuracy/latency CSVs.

Output:
  cnn/accuracy.csv   — timestamp, accuracy  (cumulative, ground truth=eMBB)
  cnn/latency.csv    — timestamp, latency_ms (end2end)
  fastinfer/accuracy.csv
  fastinfer/latency.csv
"""

import os
import re
import csv

DEMO_DIR    = os.path.dirname(os.path.abspath(__file__))
GROUND_TRUTH = 'eMBB'

CNN_LOG      = os.path.join(DEMO_DIR, 'logs-tractor-mono-mahdi-embb-32.txt')
XGB_LOG      = os.path.join(DEMO_DIR, 'logs-xgboost-mahdi-embb-32.txt')

# ── Regex patterns ─────────────────────────────────────────────────────────────

# CNN prediction line:
# 2026-01-03 10:37:18,277 INFO [UE=1.0] Predicted class: mMTC | ...
CNN_PRED_RE  = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO \[UE=[\d.]+\] Predicted class: (\w+)'
)

# CNN batch line (end2end):
# 2026-01-03 10:37:18,277 INFO [BATCH KPM ...] ... end2end=3.73 ms
CNN_BATCH_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO \[BATCH KPM .+\] .+end2end=([\d.]+) ms'
)

# XGBoost prediction line:
# 2026-01-03 10:42:17,688 INFO UE=1.0 -> Predicted class: eMBB | Latency=3.624ms | End2end=3.628ms
XGB_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) INFO UE=[\d.]+ -> Predicted class: (\w+) \| Latency=[\d.]+ms \| End2end=([\d.]+)ms'
)


# ── Parsers ────────────────────────────────────────────────────────────────────

def parse_cnn(path):
    """Returns list of (timestamp, predicted_class, end2end_ms)."""
    records = []
    pending_pred = None   # (timestamp, predicted_class) waiting for batch line

    with open(path, 'r') as f:
        for line in f:
            line = line.rstrip()

            m = CNN_PRED_RE.match(line)
            if m:
                pending_pred = (m.group(1), m.group(2))
                continue

            m = CNN_BATCH_RE.match(line)
            if m and pending_pred is not None:
                ts       = pending_pred[0]
                pred_cls = pending_pred[1]
                end2end  = float(m.group(2))
                records.append((ts, pred_cls, end2end))
                pending_pred = None

    return records


def parse_xgboost(path):
    """Returns list of (timestamp, predicted_class, end2end_ms)."""
    records = []
    with open(path, 'r') as f:
        for line in f:
            m = XGB_RE.match(line.rstrip())
            if m:
                records.append((m.group(1), m.group(2), float(m.group(3))))
    return records


# ── CSV writers ────────────────────────────────────────────────────────────────

def write_csvs(records, out_dir, ground_truth):
    os.makedirs(out_dir, exist_ok=True)

    acc_path = os.path.join(out_dir, 'accuracy.csv')
    lat_path = os.path.join(out_dir, 'latency.csv')

    correct = 0
    total   = 0

    with open(acc_path, 'w', newline='') as fa, \
         open(lat_path, 'w', newline='') as fl:

        acc_writer = csv.writer(fa)
        lat_writer = csv.writer(fl)

        acc_writer.writerow(['timestamp', 'accuracy'])
        lat_writer.writerow(['timestamp', 'latency_ms'])

        for ts, pred_cls, end2end in records:
            total   += 1
            correct += 1 if pred_cls == ground_truth else 0
            acc_writer.writerow([ts, round(correct / total, 6)])
            lat_writer.writerow([ts, end2end])

    print(f'  {out_dir}/')
    print(f'    accuracy.csv — {total} rows, final accuracy: {correct/total:.1%}')
    print(f'    latency.csv  — {total} rows')


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print('Parsing CNN/TrACTOR log...')
    cnn_records = parse_cnn(CNN_LOG)
    print(f'  Found {len(cnn_records)} predictions')
    write_csvs(cnn_records, os.path.join(DEMO_DIR, 'cnn'), GROUND_TRUTH)

    print('\nParsing XGBoost/FastInfer log...')
    xgb_records = parse_xgboost(XGB_LOG)
    print(f'  Found {len(xgb_records)} predictions')
    write_csvs(xgb_records, os.path.join(DEMO_DIR, 'fastinfer'), GROUND_TRUTH)

    print('\nDone.')


if __name__ == '__main__':
    main()
