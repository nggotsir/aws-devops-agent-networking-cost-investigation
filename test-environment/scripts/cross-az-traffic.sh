#!/bin/bash
# Cross-AZ Traffic Generator
# Run this on instance in AZ1, it sends data to instance in AZ2
# Usage: ./cross-az-traffic.sh <instance-az2-ip>

INSTANCE_AZ2_IP=$1

if [ -z "$INSTANCE_AZ2_IP" ]; then
  echo "Usage: $0 <instance-az2-ip>"
  exit 1
fi

echo "=== Cross-AZ Traffic Generator ==="
echo "Target: $INSTANCE_AZ2_IP"

while true; do
  echo "$(date) Sending 50MB cross-AZ..."
  dd if=/dev/urandom bs=1M count=50 2>/dev/null | nc -w 10 $INSTANCE_AZ2_IP 9999 2>/dev/null || true
  echo "$(date) Done, sleeping 2 minutes..."
  sleep 120
done
