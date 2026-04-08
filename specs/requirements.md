# Requirements Document

## Introduction

This document defines the requirements for the AWS Networking Cost Investigation Engine POC. The system uses AWS DevOps Agent (Frontier) as the orchestrator, with one CUR MCP server for cost data and two DevOps Agent Skills for investigation methodology. The agent handles flow log analysis and CloudWatch metrics natively.

## Glossary

- **DevOps_Agent**: AWS DevOps Agent (Frontier) — orchestrator and customer interface
- **CUR_MCP_Server**: Lambda-based MCP server querying CUR 2.0 via Athena in eu-central-1
- **flowlogs_skill**: DevOps Agent Skill teaching correct flow log + DNS correlation methodology
- **cur_correlation_skill**: DevOps Agent Skill teaching CUR + CloudWatch correlation methodology
- **CUR_2.0**: AWS Cost and Usage Report version 2 (Data Exports), Parquet format in S3
- **Flow_Logs**: VPC Flow Logs with all v5 custom fields, stored in CloudWatch Logs
- **R53_Resolver_Logs**: Route 53 Resolver query logs in CloudWatch Logs, used for IP-to-FQDN mapping

## Requirements

### Requirement 1: CUR Cost Analysis via MCP Server

**User Story:** As a customer, I want to understand where my networking costs are going, so that I can identify the biggest cost drivers and anomalies.

#### Acceptance Criteria

1. WHEN the CUR_MCP_Server receives a getNetworkingCostBreakdown request, IT SHALL return total cost, cost by service, cost by region, cost by AZ, and top spending resources classified into networking domains (NAT Gateway, VPC Endpoints, VPN, Transit Gateway, Inter-AZ, Cross-Region, ELB, S3 Transfer).
2. WHEN the CUR_MCP_Server receives a getResourceCostDetail request, IT SHALL return ALL CUR dimensions for that resource: UsageType, Operation, line item type, description, product family, from/to locations and regions, AZ, with effective cost (unblended + reservation + savings plan).
3. WHEN the CUR_MCP_Server receives a detectCostAnomalies request, IT SHALL compare current vs baseline period and return resources with >20% cost increase.
4. WHEN the CUR_MCP_Server receives a getTopNetworkingSpenders request, IT SHALL return the top N resources sorted by cost descending.
5. WHEN the CUR_MCP_Server receives a getCostTrend request, IT SHALL return cost data at hourly, daily, or weekly granularity.
6. WHEN the CUR_MCP_Server receives a getCURDataRange request, IT SHALL return the exact earliest and latest timestamps covered by available CUR data.
7. WHEN a new billing period starts, THE CUR_MCP_Server SHALL auto-discover new Athena partitions within 1 hour.

### Requirement 2: Flow Log Analysis via DevOps Agent + Skill

**User Story:** As a customer, I want to understand my network traffic patterns, so that I can correlate traffic with costs and identify savings opportunities.

#### Acceptance Criteria

1. WHEN the DevOps_Agent analyzes flow logs, IT SHALL correlate destination IPs with R53 Resolver logs to resolve FQDNs (guided by flowlogs_skill).
2. WHEN the DevOps_Agent identifies AWS service traffic, IT SHALL use dstaddr + DNS correlation for regional attribution, NEVER pkt-dst-aws-service (which doesn't distinguish regions).
3. WHEN the DevOps_Agent ranks traffic destinations, IT SHALL rank by bytes transferred from flow logs, NOT by DNS query count.
4. WHEN the DevOps_Agent calculates NAT Gateway processing cost, IT SHALL sum both ingress and egress bytes (both directions).
5. WHEN R53 Resolver logs are not available, THE DevOps_Agent SHALL fall back to raw IPs and recommend enabling resolver logging.

### Requirement 3: Investigation Orchestration

**User Story:** As a customer, I want the agent to follow a structured investigation process, so that findings are thorough and based on correlated evidence.

#### Acceptance Criteria

1. WHEN the DevOps_Agent runs a cost investigation, IT SHALL execute: CUR analysis first (via MCP), then flow log deep dive for top cost resources, then CloudWatch metrics verification, then correlated recommendations.
2. WHEN the DevOps_Agent needs CUR data, IT SHALL use the CUR MCP server tools (not attempt Athena queries directly).
3. WHEN the DevOps_Agent needs flow log or DNS data, IT SHALL query CloudWatch Logs Insights directly (not via MCP).

### Requirement 4: Investigation Report Output

**User Story:** As a customer, I want a structured investigation report with actionable recommendations.

#### Acceptance Criteria

1. THE report SHALL contain an executive summary, prioritized findings with evidence, prioritized recommendations with estimated savings and implementation steps, and data sources consulted.
2. EACH finding SHALL include severity, title, description with evidence from CUR + flow logs + metrics, affected resources, and cost impact.
3. EACH recommendation SHALL include the action, estimated savings, implementation effort, and step-by-step instructions.

### Requirement 5: MCP Server Deployment

**User Story:** As a developer, I want the MCP server deployed securely and reliably.

#### Acceptance Criteria

1. THE CUR_MCP_Server SHALL be deployed as a Lambda function in eu-central-1 (same region as CUR S3 bucket and Athena).
2. THE API Gateway SHALL require Bearer token authentication via a Lambda authorizer.
3. THE CUR_MCP_Server SHALL use the awslabs.mcp_lambda_handler library for MCP Streamable HTTP transport.
4. THE Lambda IAM role SHALL have least-privilege access: Athena, S3 (CUR bucket + results bucket), and Glue only.

### Requirement 6: Error Handling

**User Story:** As a customer, I want the system to handle missing data gracefully.

#### Acceptance Criteria

1. IF CUR data is not available, THE CUR_MCP_Server SHALL return an error with setup instructions.
2. IF an Athena query times out, THE CUR_MCP_Server SHALL retry with a narrower time range.
3. IF VPC Flow Logs are not enabled, THE DevOps_Agent SHALL continue with CUR-only analysis and recommend enabling flow logs.
4. IF R53 Resolver logs are not enabled, THE DevOps_Agent SHALL return flow log results with raw IPs and recommend enabling resolver logging.
5. IF an MCP server call fails due to permissions, THE server SHALL return which API calls failed and what permissions are needed.
