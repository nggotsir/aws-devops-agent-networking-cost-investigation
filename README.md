# AWS Networking Cost Investigation Engine (POC)

An internal investigation engine that helps customers troubleshoot cost-related issues in AWS networking services. Uses AWS DevOps Agent (Frontier) as the orchestrator with a custom CUR MCP server for cost data analysis.

## Architecture

- **DevOps Agent** — orchestrates investigations, queries CloudWatch Logs (VPC Flow Logs, R53 Resolver Logs) and CloudWatch Metrics natively
- **CUR MCP Server** — Lambda + API Gateway providing CUR 2.0 cost data via Athena (agent cannot query Athena directly)
- **DevOps Agent Skills** — guide the agent on correct investigation methodology (flow log DNS correlation, CUR/CloudWatch correlation)

## Project Structure

```
├── mcp-server/                         # Self-contained CUR MCP Server
│   ├── template.yaml                   # SAM template (API GW + Lambda + Auth)
│   ├── src/
│   │   ├── cur_mcp/handler.py          # MCP server Lambda (6 tools)
│   │   └── authorizer/handler.py       # API Gateway Bearer token authorizer
│   └── layers/mcp-deps/
│       └── requirements.txt            # awslabs.mcp_lambda_handler dependency
├── test-environment/                   # CloudFormation for multi-region test lab
│   ├── region-a.yaml                   # us-east-1: VPC, NAT GW, TGW, ALB, CloudFront
│   ├── region-b.yaml                   # eu-central-1: VPC, NAT GW, TGW
│   ├── tgw-peering.yaml               # Transit Gateway peering between regions
│   ├── athena/create_cur_table.sql     # Athena table with all CUR 2.0 columns
│   └── scripts/                        # Traffic generator scripts
├── skills/                             # DevOps Agent Skills
│   ├── flowlogs-dns-correlation/       # Flow log + R53 DNS analysis methodology
│   └── cur-cloudwatch-correlation/     # CUR vs CloudWatch reconciliation
├── docs/                               # Architecture diagrams and learnings
│   ├── POC-LEARNINGS.md
│   └── test-environment-architecture.drawio
└── .kiro/specs/                        # Design docs, requirements, task list
```

## Prerequisites

- AWS account with admin access
- AWS CLI configured
- SAM CLI installed (`brew install aws-sam-cli`)
- AWS DevOps Agent with MCP server capability enabled

## Deployment Guide

### Step 1: Deploy Test Environment (generates realistic networking cost data)

```bash
# Region A — us-east-1 (VPC, NAT GW, instances, ALB, CloudFront, TGW, flow logs)
aws cloudformation deploy \
  --template-file test-environment/region-a.yaml \
  --stack-name nci-test-region-a \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1

# Region B — eu-central-1 (VPC, NAT GW, instance, TGW, flow logs)
aws cloudformation deploy \
  --template-file test-environment/region-b.yaml \
  --stack-name nci-test-region-b \
  --capabilities CAPABILITY_NAMED_IAM \
  --region eu-central-1

# TGW Peering (after both stacks are up)
# Get TGW IDs from stack outputs, then create peering via CLI:
aws ec2 create-transit-gateway-peering-attachment \
  --transit-gateway-id <tgw-a-id> \
  --peer-transit-gateway-id <tgw-b-id> \
  --peer-region eu-central-1 \
  --peer-account-id <your-account-id> \
  --region us-east-1

# Accept peering in eu-central-1:
aws ec2 accept-transit-gateway-peering-attachment \
  --transit-gateway-attachment-id <peering-attachment-id> \
  --region eu-central-1

# Add TGW routes and VPC routes for cross-region traffic (see docs/POC-LEARNINGS.md)
```

### Step 2: Enable CUR 2.0

1. Go to AWS Console → Billing → Data Exports → Create export
2. Select CUR 2.0, Parquet format, hourly granularity
3. Choose an S3 bucket in eu-central-1
4. Wait 24-48 hours for first data delivery

### Step 3: Set up Athena (eu-central-1 — same region as CUR bucket)

```bash
# Create results bucket
aws s3 mb s3://<your-athena-results-bucket> --region eu-central-1

# Create database
aws athena start-query-execution \
  --query-string "CREATE DATABASE IF NOT EXISTS nci_cur" \
  --result-configuration OutputLocation=s3://<your-athena-results-bucket>/ \
  --region eu-central-1

# Create table — update S3 path in the SQL file first
# Then run: test-environment/athena/create_cur_table.sql

# Add partition for current billing period
aws athena start-query-execution \
  --query-string "ALTER TABLE nci_cur.cur_data ADD IF NOT EXISTS PARTITION (billing_period='2026-04') LOCATION 's3://<your-cur-bucket>/path/to/data/BILLING_PERIOD=2026-04/'" \
  --result-configuration OutputLocation=s3://<your-athena-results-bucket>/ \
  --region eu-central-1
```

### Step 4: Start Traffic Generators

Connect to instances via SSM Session Manager and run the scripts:

```bash
# On instance AZ1 (us-east-1) — main traffic generator
aws ssm start-session --target <instance-az1-id> --region us-east-1
# Then run: test-environment/scripts/traffic-generator.sh

# On instance AZ2 (us-east-1) — cross-AZ traffic
# Then run: test-environment/scripts/cross-az-traffic.sh <instance-az1-ip>

# On instance B (eu-central-1) — listener for TGW traffic
# Then run: test-environment/scripts/listener.sh
```

### Step 5: Deploy CUR MCP Server

```bash
cd mcp-server
sam build
sam deploy --stack-name nci-cur-mcp \
  --region eu-central-1 \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --parameter-overrides McpAuthToken=<your-bearer-token>
```

The output shows the MCP endpoint URL.

### Step 6: Register in DevOps Agent

1. Go to DevOps Agent console → Capability Providers → MCP Server → Register
2. Enter the endpoint URL from Step 5
3. Authentication: API Key
   - API Key Name: `bearer-auth`
   - API Key Header: `Authorization`
   - API Key Value: `Bearer <your-bearer-token>`
4. Add the MCP server to your Agent Space
5. Allowlist all 6 tools

### Step 7: Upload Skills

1. Go to DevOps Agent console → Skills → Add skill → Upload skill
2. Upload `skills/flowlogs-dns-correlation/` as a zip
3. Upload `skills/cur-cloudwatch-correlation/` as a zip

### Step 8: Test

Ask the DevOps Agent: "Investigate networking costs for account <your-account-id> for the last 7 days. Focus on NAT Gateway and Transit Gateway costs."

The agent should:
1. Call CUR MCP tools to get cost breakdown
2. Query flow logs natively for traffic patterns
3. Correlate with CloudWatch metrics
4. Provide findings and recommendations

## MCP Server Tools

| Tool | Purpose |
|---|---|
| getNetworkingCostBreakdown | Cost breakdown by service, region, AZ with top spenders |
| getResourceCostDetail | Full CUR detail for a resource — all dimensions, effective cost |
| detectCostAnomalies | Compare current vs baseline period, flag >20% increases |
| getTopNetworkingSpenders | Top N resources by networking cost |
| getCostTrend | Hourly/daily/weekly cost trends for networking services |
| getCURDataRange | Exact time range covered by available CUR data |

## Updating MCP Server Code

For quick code changes (no infrastructure changes):

```bash
cd mcp-server/src
zip -r /tmp/cur-mcp-code.zip cur_mcp/ authorizer/
aws lambda update-function-code \
  --function-name nci-cur-mcp \
  --zip-file fileb:///tmp/cur-mcp-code.zip \
  --region eu-central-1
```

For infrastructure changes (new Lambda, IAM, API Gateway):

```bash
cd mcp-server
sam build && sam deploy --stack-name nci-cur-mcp --region eu-central-1 --capabilities CAPABILITY_IAM --resolve-s3
```

## Cleanup

```bash
# Delete MCP server
aws cloudformation delete-stack --stack-name nci-cur-mcp --region eu-central-1

# Delete TGW peering first
aws ec2 delete-transit-gateway-peering-attachment --transit-gateway-attachment-id <peering-id> --region us-east-1

# Delete test environment
aws cloudformation delete-stack --stack-name nci-test-region-b --region eu-central-1
aws cloudformation delete-stack --stack-name nci-test-region-a --region us-east-1

# Delete Athena resources
aws athena start-query-execution --query-string "DROP TABLE nci_cur.cur_data" --result-configuration OutputLocation=s3://<results-bucket>/ --region eu-central-1
aws athena start-query-execution --query-string "DROP DATABASE nci_cur" --result-configuration OutputLocation=s3://<results-bucket>/ --region eu-central-1
aws s3 rb s3://<results-bucket> --force --region eu-central-1
```

## Key Learnings

See `docs/POC-LEARNINGS.md` for detailed technical findings, mistakes to avoid, and architecture decisions made during the POC.
