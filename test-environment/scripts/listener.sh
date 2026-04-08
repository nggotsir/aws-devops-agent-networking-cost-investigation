#!/bin/bash
# Simple TCP listener for receiving traffic from other instances
# Run on instances that need to receive cross-AZ or cross-region traffic
# Usage: ./listener.sh

echo "=== Starting TCP listener on port 9999 ==="
while true; do
  nc -l -p 9999 > /dev/null 2>&1
done
