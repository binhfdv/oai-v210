# Watcher KPM Moni

`watcher-kpm-moni` is a Python-based Kubernetes log watcher for OAI KPM xApps.  
It streams KPM metrics from xApp pods and saves them into CSV files for analysis.

## Features

- Watches OAI KPM xApp pods in a specified namespace.
- Captures metrics for multiple UEs per KPM block.
- Supports dynamic metric configuration via JSON or environment variables.
- Writes metrics to CSV with timestamps.
- Fully logs activity for debugging via Kubernetes pod logs.

## Requirements

- Python 3.8+
- Kubernetes cluster with OAI xApp pods.
- Python packages: `kubernetes` (if using Helm config).

## Configuration

- Metrics can be customized via environment variable `FIELDS_JSON` or a config file:
  - Default config file path: `/config/metrics.json`
  - Example metric definition:

```json
{
  "UE ID type": "UE ID type = ([\\w-]+)",
  "gnb_cu_cp_ue_e1ap": "gnb_cu_cp_ue_e1ap = (\\d+)",
  "DRB.PdcpSduVolumeDL": "DRB\\.PdcpSduVolumeDL = ([\\d.]+) \\[kb\\]"
}
```
- All configurations can be found in `values.yaml`.

## Deployment

```
$watcher-kpm-moni$ helm install watcher-kpm-moni .
$watcher-kpm-moni$ helm uninstall watcher-kpm-moni
```

Metrics data are saved as `csv` in `data/raw`

# OAI KPM Cleaner

This is a simple Python script to clean raw OAI KPM CSV files by merging CU and DU metrics per UE.

## Features

- Removes the `UE ID type` column.
- Merges CU metrics (`DRB.PdcpSduVolumeDL`, `DRB.PdcpSduVolumeUL`) into corresponding DU rows.
- Keeps the timestamp from the DU row.
- Handles multiple UE pairs in a single KPM block.
- Processes all CSV files in a folder.

## Requirements

- Python 3.8+
- Works on Linux, macOS, and Windows.

## Installation & Use

1. Clone or download this repository.
2. Make the script executable (Linux/macOS):

```bash
chmod +x oai-kpm-clean.py
./oai-kpm-clean.py <input-raw-dir> <output-clean-dir>
```
- `<input-raw-dir>`: Directory containing raw CSV files exported from OAI KPM logs.

- `<output-clean-dir>`: Directory where cleaned CSV files will be saved.

```
$watcher-kpm-moni/data$ ./oai-kpm-clean.py ./raw ./clean
```