# Implementation Plan: AWS Networking Cost Investigation Engine (POC)

## Overview

1 CUR MCP server (Lambda + API Gateway) providing CUR 2.0 cost data to DevOps Agent. Agent handles flow logs and CloudWatch natively, guided by 2 custom Skills. Test environment in us-east-1 + eu-central-1 generates realistic networking cost data.

## Completed Tasks

- [x] 1. Test environment setup
  - [x] 1.1 Deploy multi-region test lab via CloudFormation
    - Region A (us-east-1): VPC-A, 2 AZs, NAT Gateway, 2x m5.large, ALB, CloudFront, S3, TGW
    - Region B (eu-central-1): VPC-B, 1 AZ, NAT Gateway, 1x m5.large, S3, TGW
    - TGW peering (created via CLI — CloudFormation had validation issues)
    - All resources tagged auto-delete: never, Amazon Linux 2023
    - VPC Flow Logs (all v5 fields) + R53 Resolver logging on both VPCs
    - NO S3 Gateway Endpoint (intentional misconfiguration)
  - [x] 1.2 Traffic generators running
    - S3 via NAT (100MB/5min), cross-region S3, CloudFront, multiple internet destinations
    - Cross-AZ (50MB/2min), TGW cross-region (50MB/1min)
    - ncat listeners on AZ1 and eu-central-1
  - [x] 1.3 CUR 2.0 Data Export enabled and delivering data
  - [x] 1.4 Athena setup in eu-central-1 (same region as CUR bucket)
    - Database: nci_cur, Table: nci_cur.cur_data with ALL 113 CUR 2.0 columns
    - Auto-partition repair in MCP server (hourly)
  - [x] 1.5 Validated DevOps Agent CloudWatch access
    - Agent CAN query CloudWatch Metrics and Logs Insights natively
    - Agent CANNOT query Athena (blocked as mutative operation)

- [x] 2. CUR MCP Server — built and deployed
  - [x] 2.1 Rewrote MCP server using awslabs.mcp_lambda_handler (Streamable HTTP transport required by DevOps Agent)
  - [x] 2.2 Deployed Lambda + HttpApi Gateway in eu-central-1
  - [x] 2.3 Added Lambda authorizer for Bearer token auth (DevOps Agent requires auth)
  - [x] 2.4 Implemented 6 tools:
    - getNetworkingCostBreakdown — cost by service/region/AZ
    - getResourceCostDetail — full CUR dimensions (usage_type, operation, from/to regions, effective cost)
    - detectCostAnomalies — current vs baseline comparison
    - getTopNetworkingSpenders — top N by cost
    - getCostTrend — hourly/daily/weekly granularity
    - getCURDataRange — exact time range of available CUR data
  - [x] 2.5 CUR 2.0 column fixes (product_region_code, COALESCE for nulls, LIKE for ARN matching)
  - [x] 2.6 Effective cost calculation (unblended + reservation + savings plan)
  - [x] 2.7 Auto-partition repair for new billing periods
  - [x] 2.8 Registered MCP server in DevOps Agent, all tools allowlisted

- [x] 3. DevOps Agent Skills — created and uploaded
  - [x] 3.1 flowlogs-dns-correlation skill
    - Correct flow log + DNS analysis methodology
    - Never use pkt-dst-aws-service for regional attribution
    - Rank by bytes not DNS query count
  - [x] 3.2 cur-cloudwatch-correlation skill
    - CUR vs CloudWatch reconciliation methodology
    - Time period matching, unit conversion, TGW double-counting avoidance

- [x] 4. Documentation
  - [x] 4.1 Design doc updated to reflect current architecture (1 MCP server + 2 Skills)
  - [x] 4.2 Requirements doc updated
  - [x] 4.3 POC learnings documented
  - [x] 4.4 Test environment architecture diagram (draw.io)
  - [x] 4.5 README for Git publishing
  - [x] 4.6 Steering file for Kiro context continuity

## Remaining / Future Tasks

- [ ] 5. Validate end-to-end investigation flow
  - [ ] 5.1 Run a full NAT Gateway cost investigation via DevOps Agent using MCP + Skills
  - [ ] 5.2 Run a Transit Gateway cost investigation
  - [ ] 5.3 Validate CUR data matches CloudWatch metrics for overlapping time periods
  - [ ] 5.4 Test with a customer-like scenario (no prior knowledge of the environment)

- [ ] 6. Iterate on MCP server tools based on testing
  - [ ] 6.1 Add more granular queries as needed (per your peer's UsageType/Operation mapping)
  - [ ] 6.2 Add Flow Logs MCP server if agent's native analysis proves unreliable
  - [ ] 6.3 Add Athena query timeout retry with narrower time range

- [ ] 7. Reorganize project structure for Git
  - [ ] 7.1 Move MCP server code into self-contained mcp-server/ directory
  - [ ] 7.2 Clean up SAM template paths
  - [ ] 7.3 Scrub any remaining sensitive data

- [ ] 8. Future phases
  - [ ] 8.1 Production investigation (Reachability Analyzer, REJECT flows)
  - [ ] 8.2 Agentic orchestrator (if DevOps Agent proves inconsistent)
  - [ ] 8.3 Additional data sources (ALB logs, WAF, AWS Config, Transit Gateway Flow Logs)
  - [ ] 8.4 CUDOS integration, Cost Explorer anomaly triggers, Budgets alarms
  - [ ] 8.5 On-demand flow log enablement (enable on specific ENI, disable after)
  - [ ] 8.6 Own Bedrock Agent (if DevOps Agent limitations become blocking)

## Key Iterations That Happened

1. Started with 2 MCP servers (CUR + Flow Logs) → reduced to 1 (CUR only) after testing showed agent handles flow logs natively
2. Original MCP used simple HTTP POST → rewrote to use awslabs.mcp_lambda_handler for Streamable HTTP (required by DevOps Agent)
3. No auth initially → added Lambda authorizer (DevOps Agent requires auth on MCP servers)
4. getResourceCostDetail started with 3 columns → expanded to all CUR dimensions after agent requested more granularity
5. getCostTrend started daily-only → added hourly granularity for CUR/CloudWatch reconciliation
6. Added getCURDataRange tool for time period matching
7. CUR 1.0 column names → fixed to CUR 2.0 (product_region_code, etc.)
8. Athena created in wrong region (us-east-1) → moved to eu-central-1 (same as CUR bucket)
9. Added auto-partition repair for multi-month operation
10. Added effective cost (unblended + reservation + savings plan) instead of just unblended
