# NCI POC Learnings & Decisions

## Architecture Decisions

### DevOps Agent as Orchestrator
- DevOps Agent handles flow log analysis, DNS correlation, and CloudWatch metrics natively
- It CANNOT query Athena (blocked as mutative operation) — this is why we need the CUR MCP server
- Agent makes mistakes when analyzing flow logs (used pkt-dst-aws-service instead of dstaddr for region attribution) — correctable via Skills
- Agent couldn't find R53 Resolver log groups with custom paths — it assumed /aws/route53resolver

### MCP Server Architecture
- 1 MCP server (CUR only) deployed as Lambda + API Gateway in eu-central-1
- Uses `awslabs.mcp_lambda_handler` library for Streamable HTTP transport (required by DevOps Agent)
- API Gateway with Lambda authorizer for Bearer token auth (DevOps Agent requires auth on MCP servers)
- Endpoint: <your-api-gateway-url>/prod/mcp
- Auth: Bearer <your-token>

### Why Not Flow Logs MCP Server
- DevOps Agent can query CloudWatch Logs Insights natively
- Agent successfully correlated flow log IPs with R53 DNS resolver logs to get bytes per FQDN
- Created a DevOps Agent Skill (flowlogs-dns-correlation) to guide correct methodology
- May revisit if agent's analysis proves unreliable at scale

### CUR Version
- Using CUR 2.0 (Data Exports), not CUR 1.0
- CUR 2.0 has different column names (product_region_code not product_region, product map column instead of product_product_name)
- Athena table created with ALL columns from the manifest (113 columns)
- Athena in eu-central-1 (same region as CUR S3 bucket — always co-locate)

## Key Technical Findings

### Flow Logs Analysis
- pkt-dst-aws-service field shows "S3" for ALL S3 traffic regardless of region — NEVER use it for regional breakdown
- Must correlate DNS resolver logs (IP→FQDN) with flow log dstaddr to distinguish same-region vs cross-region S3
- DNS query count ≠ traffic volume — always rank by bytes from flow logs, not DNS queries
- Always calculate BOTH directions for NAT Gateway cost (ingress + egress = total processed bytes)
- Flow logs use custom format with all v5 fields enabled (including pkt-src-aws-service, pkt-dst-aws-service, az-id, traffic-path, flow-direction)

### CUR Analysis
- CUR line items for NAT Gateway: NatGateway-Bytes (data processing), NatGateway-Hours (hourly charge)
- Cross-region transfer shows as USE1-EUC1-AWS-In-Bytes / USE1-EUC1-AWS-Out-Bytes with from_region/to_region
- getResourceCostDetail must include ALL dimensions: usage_type, operation, line_item_type, description, product_family, from/to locations and regions, AZ
- Use effective cost (unblended + reservation + savings plan) not just unblended
- CUR data delivered ~once per 24 hours — CloudWatch metrics are real-time, CUR is delayed

### Athena Setup
- Athena MUST be in same region as S3 bucket (we made the mistake of putting it in us-east-1 while CUR was in eu-central-1)
- CUR 2.0 uses BILLING_PERIOD=YYYY-MM as partition key — need MSCK REPAIR TABLE for new months
- MCP server auto-repairs partitions once per hour
- Partition names are case-sensitive: S3 has BILLING_PERIOD=2026-04 but Athena partition key is lowercase billing_period — need manual ALTER TABLE ADD PARTITION

## Test Environment

### Infrastructure (2 regions)
- us-east-1: VPC-A (10.0.0.0/16), 2 AZs, NAT Gateway, 2x m5.large instances, ALB, CloudFront, S3 bucket, TGW
- eu-central-1: VPC-B (10.1.0.0/16), 1 AZ, NAT Gateway, 1x m5.large instance, S3 bucket, TGW
- TGW peering between regions (created via CLI, not CloudFormation — CF had validation issues)
- NO S3 Gateway Endpoint in VPC-A (intentional misconfiguration for testing)
- All resources tagged auto-delete: never
- Amazon Linux 2023 AMIs (not Ubuntu — had to rebuild after initial wrong AMI)

### Traffic Generators
- Main generator on AZ1: S3 via NAT (100MB), cross-region S3 from eu-central-1 (100MB), CloudFront, multiple internet destinations (Hetzner, GitHub API, httpbin, jsonplaceholder, Cloudflare, PyPI, Ubuntu ISO), TGW cross-region, yum packages — every 5 minutes
- Cross-AZ on AZ2: 50MB to AZ1 every 2 minutes
- TGW dedicated: 50MB to eu-central-1 every minute
- eu-central-1: listener on port 9999

### Data Sources
- VPC Flow Logs → CloudWatch Logs (both regions)
- R53 Resolver Query Logs → CloudWatch Logs (both regions)
- CUR 2.0 → S3 bucket <your-cur-bucket>
- Athena database: nci_cur, table: nci_cur.cur_data (eu-central-1)
- Athena results: <your-athena-results-bucket>

## Mistakes & Lessons

1. Hardcoded Ubuntu AMI labeled as Amazon Linux — always verify AMI IDs
2. Deleted entire CloudFormation stack to change AMI — should have just terminated and replaced instances
3. Created Athena in us-east-1 while CUR bucket was in eu-central-1 — always co-locate
4. ncat wasn't installed on new Amazon Linux instances — traffic generators failed silently for TGW and cross-AZ
5. SAM deploy didn't always pick up code changes — use direct `aws lambda update-function-code` for quick iterations
6. Lambda layer had wrong logical ID between builds — caused module import errors
7. API Gateway authorizer via SAM HttpApi didn't work — had to create via CLI
8. GuardDuty auto-creates VPC endpoints in new subnets — blocks CloudFormation subnet deletion
9. CloudWatch Log Groups with retention may not delete with CloudFormation stack — causes "already exists" on redeploy
10. TGW peering via CloudFormation had validation errors — created via CLI instead

## DevOps Agent Skills Created
- flowlogs-dns-correlation: Teaches agent correct flow log + DNS analysis methodology
- CUR investigation skill: TODO — create after more CUR testing

## Future Considerations
- Flow Logs MCP server: Build if agent's native analysis proves unreliable with the Skill
- On-demand flow logs: Enable flow logs only on specific ENIs during investigation, disable after (saves cost)
- Bedrock Agent: Build own agent if DevOps Agent limitations become blocking
- Database: ClickHouse or DynamoDB for investigation history (not needed for POC)
- Observability: Langfuse for agent trace visibility (not needed for POC)
- CUDOS integration, Cost Explorer anomaly detection, AWS Budgets alarm triggers (future phases)
