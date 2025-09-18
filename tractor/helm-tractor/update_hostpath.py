#!/usr/bin/env python3
import os
import sys
from ruamel.yaml import YAML

# Map filenames to subchart values.yaml keys and mount paths
mount_map = {
    "embb1010123456002_metrics.csv": ("tractor-kpm-simu/values.yaml", "kpisCsv", "/app/kpis.csv"),
    "model.32.cnn.pt": ("tractor-model/values.yaml", "model", "/mnt/model/model.pt"),
    "cols_maxmin.pkl": ("tractor-normalizer/values.yaml", "norm", "/mnt/model/norm.pkl")
}

def find_src_folder():
    """Find the nearest 'src' folder up the directory tree from current path."""
    path = os.getcwd()
    while True:
        candidate = os.path.join(path, "src")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(path)
        if parent == path:  # reached root
            break
        path = parent
    return None

def find_file_in_src(filename, src_root):
    """Recursively search for a file inside src_root."""
    for root, dirs, files in os.walk(src_root):
        if filename in files:
            return os.path.abspath(os.path.join(root, filename))
    return None

def main():
    # If no filenames provided, use all defaults
    if len(sys.argv) < 2:
        filenames = list(mount_map.keys())
        print("No filenames provided. Updating all known files:", filenames)
    else:
        filenames = sys.argv[1:]

    src_root = find_src_folder()
    if not src_root:
        print("Error: Could not find 'src/' folder in parent directories.", file=sys.stderr)
        sys.exit(1)

    yaml = YAML()
    yaml.preserve_quotes = True  # preserve quotes if any

    for fname in filenames:
        if fname not in mount_map:
            print(f"Skipping unknown file: {fname}")
            continue

        values_file, vol_key, mount_path = mount_map[fname]

        abs_path = find_file_in_src(fname, src_root)
        if not abs_path:
            print(f"Error: {fname} not found in src/ folder.", file=sys.stderr)
            continue

        print(f"Updating {values_file} with {fname} -> {abs_path}")

        if not os.path.exists(values_file):
            print(f"Error: {values_file} not found.", file=sys.stderr)
            continue

        # Load YAML
        with open(values_file, "r") as f:
            values = yaml.load(f) or {}

        if "volumeMounts" not in values or values["volumeMounts"] is None:
            values["volumeMounts"] = {}

        # ✅ Ensure hostPath is always a string
        values["volumeMounts"][vol_key] = {"hostPath": str(abs_path), "mountPath": mount_path}

        # Save YAML back
        with open(values_file, "w") as f:
            yaml.dump(values, f)

    print("All hostPaths updated successfully.")

if __name__ == "__main__":
    main()
