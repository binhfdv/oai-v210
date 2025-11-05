#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

# Simple retry helper for apt to be resilient in flaky networks
retry() {
  local n=0
  local max=5
  until "$@" ; do
    n=$((n+1))
    if [ $n -ge $max ]; then
      echo "Command failed after $n attempts: $*"
      return 1
    fi
    echo "Command failed, retrying ($n/$max) ..."
    sleep 2
  done
}

retry apt update

retry apt install -y --no-install-recommends \
  iputils-ping iproute2 tcpdump netcat-openbsd curl tcpreplay \
  automake build-essential libpcap-dev python3 python3-pip

# Cleanup apt cache
apt-get clean
rm -rf /var/lib/apt/lists/*

# Install Scapy via pip
pip3 install --no-cache-dir scapy

echo "All done. Installed: iputils-ping, iproute2, tcpdump, netcat, curl, tcpreplay, automake, build-essential, libpcap-dev, python3, pip3, scapy"
