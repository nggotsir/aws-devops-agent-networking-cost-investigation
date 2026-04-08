#!/bin/bash
# Traffic Generator for NCI POC Test Environment
# Run this on instances in VPC-A (us-east-1) private subnets
# Usage: ./traffic-generator.sh <s3-bucket-a> <s3-bucket-b> <cloudfront-domain> <instance-b-ip>

S3_BUCKET_A=$1
S3_BUCKET_B=$2
CF_DOMAIN=$3
INSTANCE_B_IP=$4

if [ -z "$S3_BUCKET_A" ] || [ -z "$S3_BUCKET_B" ]; then
  echo "Usage: $0 <s3-bucket-a> <s3-bucket-b> <cloudfront-domain> <instance-b-ip>"
  exit 1
fi

echo "=== NCI Traffic Generator ==="
echo "S3 Bucket A: $S3_BUCKET_A"
echo "S3 Bucket B: $S3_BUCKET_B"
echo "CloudFront: $CF_DOMAIN"
echo "Instance B: $INSTANCE_B_IP"

# Generate a 100MB test file for transfers
echo "Creating 100MB test file..."
dd if=/dev/urandom of=/tmp/testfile-100mb bs=1M count=100 2>/dev/null

# Upload test file to both S3 buckets
echo "Uploading test files to S3..."
aws s3 cp /tmp/testfile-100mb s3://$S3_BUCKET_A/testfile-100mb
aws s3 cp /tmp/testfile-100mb s3://$S3_BUCKET_B/testfile-100mb

while true; do
  echo "$(date) --- Starting traffic generation cycle ---"

  # 1. S3 through NAT Gateway (no VPC endpoint - the misconfiguration)
  echo "$(date) [NAT-S3] Downloading from S3 through NAT Gateway..."
  aws s3 cp s3://$S3_BUCKET_A/testfile-100mb /tmp/s3-download-a 2>/dev/null
  rm -f /tmp/s3-download-a

  # 2. Cross-region S3 download (us-east-1 instance downloading from eu-central-1 bucket)
  echo "$(date) [CROSS-REGION-S3] Downloading from S3 in eu-central-1..."
  aws s3 cp s3://$S3_BUCKET_B/testfile-100mb /tmp/s3-download-b --region eu-central-1 2>/dev/null
  rm -f /tmp/s3-download-b

  # 3. CloudFront download (instance fetching S3 content via CloudFront through NAT)
  if [ -n "$CF_DOMAIN" ]; then
    echo "$(date) [CLOUDFRONT] Downloading via CloudFront..."
    curl -s -o /tmp/cf-download "https://$CF_DOMAIN/testfile-100mb" 2>/dev/null
    rm -f /tmp/cf-download
  fi

  # 4. Internet downloads through NAT
  echo "$(date) [INTERNET] Downloading from internet through NAT..."
  curl -s -o /tmp/internet-download "https://speed.hetzner.de/100MB.bin" 2>/dev/null
  rm -f /tmp/internet-download

  # 5. Cross-region via TGW (if instance B IP provided)
  if [ -n "$INSTANCE_B_IP" ]; then
    echo "$(date) [TGW] Sending data to instance in eu-central-1 via TGW..."
    dd if=/dev/urandom bs=1M count=10 2>/dev/null | nc -w 5 $INSTANCE_B_IP 9999 2>/dev/null || true
  fi

  # 6. Package manager updates (generates DNS queries + NAT traffic)
  echo "$(date) [PACKAGES] Running package check..."
  yum check-update -q 2>/dev/null || true

  echo "$(date) --- Cycle complete, sleeping 5 minutes ---"
  sleep 300
done
