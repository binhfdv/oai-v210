#!/usr/bin/env bash
set -euo pipefail

# === Configurable parameters ===
FOLDER="$1"                     # Folder containing pcap files
REPLAY_SCRIPT="./replay_pcap.sh"
LOGDIR="./replay_logs"          # Folder for logs
SLEEP_BETWEEN=2                 # Seconds between pcaps (set 0 for none)

# === Input validation ===
if [ $# -lt 1 ]; then
  echo "Usage: $0 <pcap_folder>"
  exit 1
fi

if [ ! -d "$FOLDER" ]; then
  echo "❌ Folder does not exist: $FOLDER"
  exit 1
fi

if [ ! -x "$REPLAY_SCRIPT" ]; then
  echo "❌ replay_pcap.sh not found or not executable: $REPLAY_SCRIPT"
  exit 1
fi

mkdir -p "$LOGDIR"

echo "========================================"
echo "📁 PCAP Folder:   $FOLDER"
echo "📜 Replay Script: $REPLAY_SCRIPT"
echo "📝 Log folder:    $LOGDIR"
echo "========================================"
echo

# === Find all .pcap files ===
mapfile -t PCAPS < <(find "$FOLDER" -type f -name "*.pcap" | sort)

if [ ${#PCAPS[@]} -eq 0 ]; then
  echo "⚠️ No .pcap files found in folder."
  exit 0
fi

echo "🔍 Found ${#PCAPS[@]} pcap files."
echo

# === Replay loop ===
for pcap in "${PCAPS[@]}"; do
  base=$(basename "$pcap")
  log="$LOGDIR/$base.log"

  echo "=============================="
  echo "▶️ Replaying: $base"
  echo "📝 Log:       $log"
  echo "=============================="

  # Call your replay script
  if "$REPLAY_SCRIPT" "$pcap" &> "$log"; then
    echo "✅ Completed: $base"
  else
    echo "❌ ERROR during replay of $base. Check log: $log"
  fi

  if [ "$SLEEP_BETWEEN" -gt 0 ]; then
    echo "⏳ Waiting $SLEEP_BETWEEN seconds..."
    sleep "$SLEEP_BETWEEN"
  fi

  echo
done

echo "========================================"
echo "🎉 All PCAPs processed."
echo "========================================"
