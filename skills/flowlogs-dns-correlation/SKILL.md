---
name: flowlogs-dns-correlation
description: Analyze VPC Flow Logs traffic to identify top destinations by actual data volume, with accurate cross-region AWS service attribution using Route 53 DNS Resolver logs correlation.
---

# FlowLogs Analysis with R53 DNS Logs Correlation

## Purpose

Analyze VPC Flow Logs traffic to identify top destinations by actual data volume, with accurate cross-region AWS service attribution using Route 53 DNS Resolver logs correlation.

## Key Principles

### 1. Always correlate DNS logs with Flow Logs by IP address

- DNS resolver logs show which domains resolved to which IPs
- Flow Logs show actual bytes transferred to those IPs
- Never rely on DNS query count as a proxy for traffic volume

### 2. Never use `pkt-dst-aws-service` to distinguish regions

- This field shows "S3" for ALL S3 traffic regardless of region
- Same applies to other AWS services (DynamoDB, etc.)
- Always match resolved IPs against `dstaddr`/`srcaddr` in Flow Logs

### 3. Ask for log group paths — don't assume

- Standard paths like `/aws/route53resolver` or `/aws/vpc-flow-logs` are often wrong
- Custom deployments use custom paths (e.g., `/nci/r53-resolver/vpc-a`)
- Discover or confirm log group names before querying

### 4. Calculate BOTH directions for processing-based charges

NAT Gateway and Transit Gateway charge per GB of **data processed**, not per GB in a single direction.

| Service | Charge Type | What to Measure |
|---------|-------------|-----------------|
| NAT Gateway | $0.045/GB processed | Ingress bytes + Egress bytes |
| Transit Gateway | $0.02/GB processed | Ingress bytes + Egress bytes |

A common mistake is analyzing only egress (outbound) traffic. For accurate cost attribution:
1. Query Flow Logs for traffic **TO** destination IPs (egress/uploads)
2. Query Flow Logs for traffic **FROM** those IPs (ingress/downloads)
3. **Sum both** for total processed bytes

Example: If an S3 bucket shows 500 MB egress but 12 GB ingress, the NAT Gateway cost is based on **12.5 GB**, not 500 MB.

## Methodology

### Step 1: Identify traffic sources

- Query Flow Logs to find top internal IPs by bytes
- Map private IPs to EC2 instances using `describe-instances`

### Step 2: Get DNS resolutions

- Query DNS resolver logs for domains resolved by those source IPs
- Extract domain → IP mappings from answer records (`rdata` or `answers.0.Rdata`)

### Step 3: Correlate by destination IP

For each domain of interest (especially cross-region AWS services):

1. Get all resolved IPs from DNS logs
2. Query Flow Logs filtering by `dstaddr` matching those IPs
3. Sum `bytes` to get actual traffic volume

### Step 4: Rank by actual bytes, not query count

- Present destinations ranked by total bytes transferred
- Include both directions (bytes sent and received)
- A domain with 1 DNS query could transfer 10 GB; a domain with 100 queries could transfer 1 KB

## Common Pitfalls

| Pitfall | Why It's Wrong | Correct Approach |
|---------|----------------|------------------|
| Ranking by DNS query count | A domain queried 16 times could transfer 1 KB or 100 GB | Rank by bytes from Flow Logs |
| Using `pkt-dst-aws-service` for regional breakdown | Shows "S3" for all regions | Correlate DNS-resolved IPs with `dstaddr` |
| Assuming standard log group paths | Custom deployments vary | Ask or discover log groups first |
| Grouping all S3 as "regional" | Cross-region S3 has different cost implications | Identify bucket region from DNS domain, correlate IPs |

## Query Templates

### DNS Resolver Logs — Get resolved IPs for a cross-region S3 bucket

```sql
fields @timestamp, query_name, answers.0.Rdata as resolved_ip
| filter query_name like /your-bucket-name.*s3\.eu-central-1/
| filter ispresent(resolved_ip)
| stats count() by resolved_ip
```

### DNS Resolver Logs — Top domains by query count (use only for discovery, not ranking)

```sql
fields query_name
| stats count() as query_count by query_name
| sort query_count desc
| limit 20
```

### Flow Logs — Get bytes for specific destination IPs

```sql
fields @timestamp, srcaddr, dstaddr, bytes
| filter dstaddr like /^52\.219\.47\./
   or dstaddr like /^3\.5\.136\./
| stats sum(bytes) as total_bytes by dstaddr
| sort total_bytes desc
```

### Flow Logs — Top destinations by bytes

```sql
fields srcaddr, dstaddr, bytes
| filter srcaddr like /^10\.0\./ -- adjust for your VPC CIDR
| stats sum(bytes) as total_bytes by dstaddr
| sort total_bytes desc
| limit 20
```

### Flow Logs — Bidirectional traffic for specific IPs

```sql
fields @timestamp, srcaddr, dstaddr, bytes, flow_direction
| filter dstaddr in ['52.219.47.41', '3.5.136.77'] 
   or srcaddr in ['52.219.47.41', '3.5.136.77']
| stats sum(bytes) as total_bytes by srcaddr, dstaddr
```

## Summary

- DNS query count ≠ traffic volume — always correlate with Flow Log bytes
- pkt-dst-aws-service ≠ regional breakdown — always correlate by IP
- Confirm log group paths — don't assume standard naming
- Correlate by IP — DNS logs → resolved IPs → Flow Logs dstaddr/srcaddr → bytes
