#!/usr/bin/env python3
import os
import sys
from ruamel.yaml import YAML

# Map filenames to subchart values.yaml keys
pv_map = {
    "embb1010123456002_metrics.csv": ("tractor-kpm-simu/values.yaml", "persistentVolume"),
    "model.32.cnn.pt": ("tractor-model/values.yaml", "persistentVolume"),
    "cols_maxmin.pkl": ("tractor-normalizer/values.yaml", "persistentVolume")
}

def find_src_folder():
    """Find the nearest 'src' folder up the directory tree from current path."""
    path = os.getcwd()
    while True:
        candidate = os.path.join(path, "src")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(path)
        if parent == path:
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
    if len(sys.argv) < 2:
        print("Usage: ./update_hostpath.py <file1> <file2> ...")
        sys.exit(1)

    filenames = sys.argv[1:]
    src_root = find_src_folder()
    if not src_root:
        print("Error: Could not find 'src/' folder in parent directories.", file=sys.stderr)
        sys.exit(1)

    yaml = YAML()
    yaml.preserve_quotes = True

    for fname in filenames:
        if fname not in pv_map:
            print(f"Skipping unknown file: {fname}")
            continue

        values_file, pv_key = pv_map[fname]
        abs_file_path = find_file_in_src(fname, src_root)
        if not abs_file_path:
            print(f"Error: {fname} not found in src/ folder.", file=sys.stderr)
            continue

        # Use directory for hostPath
        abs_path = os.path.dirname(abs_file_path)

        if not os.path.exists(values_file):
            print(f"Error: {values_file} not found.", file=sys.stderr)
            continue

        print(f"Updating {values_file} persistentVolume.hostPath -> {abs_path}")

        # Load YAML
        with open(values_file, "r") as f:
            values = yaml.load(f) or {}

        if pv_key not in values or values[pv_key] is None:
            values[pv_key] = {}

        # Update hostPath
        values[pv_key]["hostPath"] = abs_path

        # Save YAML back
        with open(values_file, "w") as f:
            yaml.dump(values, f)

    print("All hostPaths in values.yaml updated successfully.")

if __name__ == "__main__":
    main()
