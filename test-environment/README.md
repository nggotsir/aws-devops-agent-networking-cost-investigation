# Test Environment for Networking Cost Investigation POC

## Overview
Multi-region test lab that generates realistic networking cost data for the POC.

## Stacks (deploy in order)
1. `region-a.yaml` — Deploy to us-east-1
2. `region-b.yaml` — Deploy to eu-central-1
3. `tgw-peering.yaml` — Deploy to us-east-1 (after both regional stacks)

## Deploy
```bash
# Step 1: Region A (us-east-1)
aws cloudformation deploy \
  --template-file infra/test-environment/region-a.yaml \
  --stack-name nci-test-region-a \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# Step 2: Region B (eu-central-1)
aws cloudformation deploy \
  --template-file infra/test-environment/region-b.yaml \
  --stack-name nci-test-region-b \
  --capabilities CAPABILITY_NAMED_IAM \
  --region eu-central-1

# Step 3: TGW Peering (us-east-1, after both stacks are up)
# Get TGW IDs from stack outputs first:
TGW_A=$(aws cloudformation describe-stacks --stack-name nci-test-region-a --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`TransitGatewayAId`].OutputValue' --output text)
TGW_B=$(aws cloudformation describe-stacks --stack-name nci-test-region-b --region eu-central-1 --query 'Stacks[0].Outputs[?OutputKey==`TransitGatewayBId`].OutputValue' --output text)

aws cloudformation deploy \
  --template-file infra/test-environment/tgw-peering.yaml \
  --stack-name nci-test-tgw-peering \
  --region us-east-1 \
  --parameter-overrides TGWAId=$TGW_A TGWBId=$TGW_B

# Step 4: Accept TGW peering in eu-central-1 (manual)
# Get peering attachment ID and accept it

# Step 5: Enable CUR 2.0 (manual — cannot be done via CloudFormation)
# Go to Billing → Data Exports → Create export
# Select CUR 2.0, configure S3 bucket, enable Athena integration
```

## Connect to instances (no key pair needed)
```bash
# Use SSM Session Manager
aws ssm start-session --target <instance-id> --region us-east-1
```

## Cleanup
```bash
aws cloudformation delete-stack --stack-name nci-test-tgw-peering --region us-east-1
aws cloudformation delete-stack --stack-name nci-test-region-b --region eu-central-1
aws cloudformation delete-stack --stack-name nci-test-region-a --region us-east-1
```

## Tags
All resources tagged with `auto-delete: never` to prevent automatic cleanup.
