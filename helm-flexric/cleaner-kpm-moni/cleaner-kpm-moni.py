import csv
import os
import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

RAW_DIR = os.getenv("RAW_DIR", "/data/raw")
CLEAN_DIR = os.getenv("CLEAN_DIR", "/data/clean")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cleaner")

# In-memory cache for CU rows per UE
cu_cache = {}

def is_number(s):
    """Return True if s is numeric (int or float)."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def normalize_ue_id(row):
    """
    Ensure ran_ue_id is numeric. If not, use gnb_cu_ue_f1ap or gnb_cu_cp_ue_e1ap.
    """
    ran_ue_id = row.get("ran_ue_id", "")
    if not is_number(ran_ue_id):
        # Try alternative IDs
        alt = row.get("gnb_cu_ue_f1ap", "") or row.get("gnb_cu_cp_ue_e1ap", "")
        if alt:
            row["ran_ue_id"] = alt
    return row

def clean_kpm_file(input_file, output_file):
    try:
        with open(input_file, "r") as f_in:
            reader = csv.DictReader(f_in)
            fields = [f for f in reader.fieldnames if f != "UE ID type"]
            rows = list(reader)

        if not rows:
            return

        cleaned_rows = []

        for row in rows:
            # Step 1: Normalize UE ID field
            row = normalize_ue_id(row)

            ue_type = row.get("UE ID type", "")
            ran_ue_id = row.get("ran_ue_id", "")
            if not ran_ue_id:
                continue

            # Step 2: Separate CU and DU
            if "CU" in ue_type:
                cu_cache[ran_ue_id] = row
            elif "DU" in ue_type:
                merged = row.copy()

                # Step 3: Merge CU metrics if available
                if ran_ue_id in cu_cache:
                    cu_row = cu_cache[ran_ue_id]
                    merged["gnb_cu_cp_ue_e1ap"] = cu_row.get("gnb_cu_cp_ue_e1ap", "")
                    merged["DRB.PdcpSduVolumeDL"] = cu_row.get("DRB.PdcpSduVolumeDL", "")
                    merged["DRB.PdcpSduVolumeUL"] = cu_row.get("DRB.PdcpSduVolumeUL", "")

                merged.pop("UE ID type", None)
                cleaned_rows.append(merged)

        if cleaned_rows:
            os.makedirs(CLEAN_DIR, exist_ok=True)
            with open(output_file, "w", newline="") as f_out:
                writer = csv.DictWriter(f_out, fieldnames=fields)
                writer.writeheader()
                writer.writerows(cleaned_rows)
            logger.info(
                f"Cleaned: {input_file} -> {output_file} ({len(cleaned_rows)} rows)"
            )

    except Exception as e:
        logger.error(f"Error cleaning {input_file}: {e}")

class KPMFileHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith(".csv"):
            return
        input_file = Path(event.src_path)
        output_file = Path(CLEAN_DIR) / input_file.name
        clean_kpm_file(input_file, output_file)

def main():
    Path(CLEAN_DIR).mkdir(parents=True, exist_ok=True)
    observer = Observer()
    handler = KPMFileHandler()
    observer.schedule(handler, RAW_DIR, recursive=False)
    observer.start()
    logger.info(f"Watching {RAW_DIR} for new or updated CSVs...")

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    main()
