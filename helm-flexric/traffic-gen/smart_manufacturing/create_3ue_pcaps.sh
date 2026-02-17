#!/bin/bash
# Automated script to create all 3 UE PCAPs from CSV files
# This script assumes you've already run split_csv_by_ue.py

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "3-UE PCAP Creation Script"
echo "=========================================="
echo ""

# Check if CSV files exist
if [ ! -f "ue1_urllc_data.csv" ]; then
    echo "[ERROR] ue1_urllc_data.csv not found!"
    echo "[INFO] Run: python3 split_csv_by_ue.py data_communications.csv device_to_ue_mapping.csv"
    exit 1
fi

if [ ! -f "ue2_embb_data.csv" ]; then
    echo "[ERROR] ue2_embb_data.csv not found!"
    exit 1
fi

if [ ! -f "ue3_mmtc_data.csv" ]; then
    echo "[ERROR] ue3_mmtc_data.csv not found!"
    exit 1
fi

# Create output directory
mkdir -p ue_pcaps

echo "[INFO] Creating PCAPs with UE IPs (in 5 chunks of 20% each):"
echo "  UE1 (URLLC): 12.1.1.100"
echo "  UE2 (eMBB):  12.1.1.101"
echo "  UE3 (mMTC):  12.1.1.102"
echo ""
echo "[INFO] Each CSV will be split into 5 parts (20% each)"
echo ""

# Convert UE1 (in 5 chunks)
echo "=========================================="
echo "Converting UE1 (URLLC) - 5 chunks..."
echo "=========================================="
python3 convert_3ue_to_pcap.py ue1_urllc_data.csv ue_pcaps/ue1_urllc --auto --chunks 5

echo ""
echo "=========================================="
echo "Converting UE2 (eMBB) - 5 chunks..."
echo "=========================================="
python3 convert_3ue_to_pcap.py ue2_embb_data.csv ue_pcaps/ue2_embb --auto --chunks 5

echo ""
echo "=========================================="
echo "Converting UE3 (mMTC) - 5 chunks..."
echo "=========================================="
python3 convert_3ue_to_pcap.py ue3_mmtc_data.csv ue_pcaps/ue3_mmtc --auto --chunks 5

echo ""
echo "=========================================="
echo "PCAP Creation Complete!"
echo "=========================================="
echo ""
echo "Output files (15 total - 5 per UE):"
ls -lh ue_pcaps/*.pcap | head -20
echo ""
echo "To replay UE1 traffic (all 5 parts):"
echo "  for i in {1..5}; do"
echo "    sudo tcpreplay -i oaitun_ue1 -p 10 ue_pcaps/ue1_urllc_part\$i.pcap"
echo "  done"
echo ""
echo "To replay UE2 traffic (all 5 parts):"
echo "  for i in {1..5}; do"
echo "    sudo tcpreplay -i oaitun_ue2 -p 10 ue_pcaps/ue2_embb_part\$i.pcap"
echo "  done"
echo ""
echo "To replay UE3 traffic (all 5 parts):"
echo "  for i in {1..5}; do"
echo "    sudo tcpreplay -i oaitun_ue3 -p 10 ue_pcaps/ue3_mmtc_part\$i.pcap"
echo "  done"
echo ""
