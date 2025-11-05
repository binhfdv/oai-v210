#!/usr/bin/env bash
# Purpose: Find which veth interface carries UDP/9050 traffic (from tcpreplay)

PORT=9050
DURATION=3   # seconds to capture per interface

echo "🔎 Scanning veth interfaces attached to cni0 for UDP port $PORT traffic ..."
echo

# Extract veth names from 'bridge link show'
IFACES=$(bridge link show | awk '{print $2}' | cut -d'@' -f1 | grep '^veth')

for IFACE in $IFACES; do
  if ip link show dev "$IFACE" >/dev/null 2>&1; then
    echo "▶ Testing $IFACE ..."
    # Run tcpdump briefly (timeout avoids hanging)
    sudo timeout "$DURATION" tcpdump -i "$IFACE" -nn -q udp port "$PORT" -c 5 2>/tmp/tcpdump_${IFACE}.log >/dev/null
    PACKETS=$(grep -c 'IP ' /tmp/tcpdump_${IFACE}.log)
    if [ "$PACKETS" -gt 0 ]; then
      echo "✅ $IFACE is ACTIVE ($PACKETS packets detected on UDP port $PORT)"
      echo "---- Sample output ----"
      head -n 5 /tmp/tcpdump_${IFACE}.log
      echo "------------------------"
    else
      echo "❌ $IFACE inactive (no UDP:$PORT traffic)"
    fi
  else
    echo "⚠️  Interface $IFACE not found"
  fi
  echo
done

echo "✅ Scan complete."
