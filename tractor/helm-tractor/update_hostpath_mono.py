#!/usr/bin/env python3
import os
import sys
from ruamel.yaml import YAML

# Mapping of filenames to keys inside the monolithic values.yaml
pv_map = {
    "model.32.cnn.pt": ("persistentVolume.model", "tractor-mono/values.yaml"),
    "cols_maxmin.pkl": ("persistentVolume.norm",  "tractor-mono/values.yaml"),
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

def set_nested_key(data, dotted_key, value):
    """Set nested YAML key using dotted path notation (e.g., 'a.b.c')."""
    keys = dotted_key.split(".")
    for k in keys[:-1]:
        if k not in data or data[k] is None:
            data[k] = {}
        data = data[k]
    data[keys[-1]] = value

def main():
    if len(sys.argv) < 2:
        print("Usage: ./update_hostpath_mono.py <file1> <file2> ...")
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

        key_path, values_file = pv_map[fname]
        abs_file_path = find_file_in_src(fname, src_root)
        if not abs_file_path:
            print(f"Error: {fname} not found in src/ folder.", file=sys.stderr)
            continue

        abs_dir = os.path.dirname(abs_file_path)
        if not os.path.exists(values_file):
            print(f"Error: {values_file} not found.", file=sys.stderr)
            continue

        print(f"Updating {values_file} -> {key_path}.hostPath = {abs_dir}")

        # Load YAML
        with open(values_file, "r") as f:
            values = yaml.load(f) or {}

        # Navigate to nested key (persistentVolume.model or persistentVolume.norm)
        target = values
        keys = key_path.split(".")
        for k in keys:
            if k not in target or target[k] is None:
                target[k] = {}
            target = target[k]

        # Update hostPath
        target["hostPath"] = abs_dir

        # Save YAML back
        with open(values_file, "w") as f:
            yaml.dump(values, f)

    print("All hostPaths in tractor-mono/values.yaml updated successfully.")

if __name__ == "__main__":
    main()
