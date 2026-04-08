---
name: cur-cloudwatch-correlation
description: Reconcile AWS Cost and Usage Report (CUR) data with CloudWatch metrics to validate billing accuracy, identify data lag, and troubleshoot cost discrepancies for networking resources.
---

# CUR-CloudWatch Billing Reconciliation

## Purpose

Reconcile AWS Cost and Usage Report (CUR) data with CloudWatch metrics to validate billing accuracy, identify data lag, and troubleshoot cost discrepancies for networking resources (NAT Gateway, Transit Gateway, VPC Endpoints, Load Balancers).

## Key Principles

### 1. CUR lags CloudWatch by 24-48 hours
- CUR data is processed in batches, not real-time
- New resources may take 1-3 days to appear fully in CUR
- Always identify which time periods exist in CUR before comparing

### 2. Always correlate by matching exact time periods
- Don't compare "total CUR" vs "total CloudWatch" for a date range
- First: identify which hours/days have CUR records
- Then: query CloudWatch for only those same periods
- Mismatched periods are the #1 cause of apparent discrepancies

### 3. CUR usage quantities are in GB (or GigaBytes)
- CloudWatch metrics are typically in Bytes
- Conversion: `CUR_GB × 1024³ = CloudWatch_Bytes`
- Example: `4.694e-07 GB × 1,073,741,824 = 504 bytes`

### 4. Transit Gateway CloudWatch metrics double-count at aggregate level
- Querying by `TransitGateway` dimension alone aggregates all attachments
- Traffic entering from VPC attachment AND exiting to peering attachment both counted
- Query at `TransitGateway + TransitGatewayAttachment` level for accurate per-flow data

### 5. CUR bills data processing, not directional bytes

| Resource | CUR Usage Type | What It Measures |
|----------|---------------|------------------|
| NAT Gateway | `NatGateway-Bytes` | Bytes processed (in + out) |
| Transit Gateway | `TransitGateway-Bytes` | Bytes processed per attachment |
| Transit Gateway | `*-AWS-Out-Bytes` | Cross-region peering transfer |

## Methodology

### Step 1: Get CUR data with time granularity

Query CUR to see exactly which time periods have billing records:

```sql
SELECT 
  line_item_usage_start_date,
  line_item_usage_end_date,
  line_item_usage_type,
  line_item_operation,
  line_item_usage_amount,
  pricing_unit
FROM cur_reports
WHERE line_item_resource_id = 'tgw-xxxxx'
  AND line_item_usage_type LIKE '%Bytes%'
ORDER BY line_item_usage_start_date
```

Or use the CUR MCP tool:
`getResourceCostDetail(resource_id, start_date, end_date)`

Note: The MCP tool aggregates data — for hourly granularity, use Athena directly.

### Step 2: Query CloudWatch for matching periods only

Once you know CUR covers (for example) April 6th 13:00-14:00 UTC:

```python
get_metric_statistics(
  Namespace='AWS/TransitGateway',
  MetricName='BytesIn',
  Dimensions=[
    {'Name': 'TransitGateway', 'Value': 'tgw-xxxxx'},
    {'Name': 'TransitGatewayAttachment', 'Value': 'tgw-attach-xxxxx'}
  ],
  StartTime='2026-04-06T13:00:00Z',
  EndTime='2026-04-06T14:00:00Z',
  Period=3600,
  Statistics=['Sum']
)
```

### Step 3: Convert units and compare

| Source | Raw Value | Converted |
|--------|-----------|-----------|
| CUR | 4.694e-07 GB | 504 bytes |
| CloudWatch | 504 bytes | 504 bytes |
| Match? | ✅ | ✅ |

### Step 4: Identify unreconciled periods

- Traffic in CloudWatch but not in CUR = CUR lag (expected for recent data)
- Traffic in CUR but not in CloudWatch = Investigate (possible metric gap or resource ID mismatch)

## Transit Gateway Specifics

### CloudWatch Dimension Hierarchy

Transit Gateway metrics exist at multiple levels:

| Dimensions | What It Shows |
|-----------|---------------|
| TransitGateway only | Aggregate across all attachments (may double-count) |
| TransitGateway + TransitGatewayAttachment | Per-attachment traffic (accurate) |
| TransitGateway + TransitGatewayAttachment + AvailabilityZone | Per-AZ breakdown |

Always query at the attachment level to avoid double-counting when traffic flows through multiple attachments.

### Understanding Traffic Flow

For a VPC → TGW → Peering flow:
- VPC Attachment: BytesIn=3GB, BytesOut=7MB (traffic entering TGW from VPC)
- Peering Attachment: BytesIn=7MB, BytesOut=3GB (traffic exiting TGW to peer)

The actual data transfer is ~3GB, but TGW-level aggregate would show ~6GB.

### CUR Usage Types for Transit Gateway

| Usage Type Pattern | Meaning |
|-------------------|---------|
| USE1-TransitGateway-Bytes | VPC attachment processing in us-east-1 |
| USE1-EUC1-AWS-Out-Bytes | Cross-region transfer us-east-1 → eu-central-1 |
| TransitGatewayVPC operation | Traffic through VPC attachment |
| TGWPeering-Out operation | Traffic through peering attachment |

## NAT Gateway Specifics

### CloudWatch Dimensions

| Dimensions | Metrics |
|-----------|---------|
| NatGatewayId | BytesInFromDestination, BytesInFromSource, BytesOutToDestination, BytesOutToSource |

### Mapping CloudWatch to CUR

| CloudWatch Metric | Direction | CUR Equivalent |
|------------------|-----------|----------------|
| BytesOutToDestination | EC2 → NAT → Internet | NatGateway-Bytes (egress portion) |
| BytesInFromDestination | Internet → NAT → EC2 | NatGateway-Bytes (ingress portion) |

Total billable = BytesOutToDestination + BytesInFromDestination

## Common Discrepancy Causes

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| CUR shows much less than CloudWatch | CUR lag (24-48h) | Wait or compare only overlapping periods |
| CUR shows more than CloudWatch | Resource ID mismatch, or metric retention expired | Verify resource IDs match |
| Numbers close but not exact | Rounding, sampling differences | Acceptable variance < 1% |
| CUR shows $0 cost but has usage | Free tier, or RI/SP coverage | Check line_item_line_item_type |

## Query Templates

### Athena: CUR hourly detail for a resource

```sql
SELECT 
  line_item_usage_start_date,
  line_item_usage_end_date,
  line_item_usage_type,
  line_item_operation,
  line_item_usage_amount,
  line_item_unblended_cost,
  pricing_unit
FROM cur_reports.cur_reports
WHERE line_item_resource_id = 'nat-xxxxx'
  AND line_item_usage_start_date >= timestamp '2026-04-01'
  AND line_item_usage_type LIKE '%Bytes%'
ORDER BY line_item_usage_start_date
```

### CloudWatch: List available metrics for a TGW

```python
list_metrics(
  Namespace='AWS/TransitGateway',
  Dimensions=[{'Name': 'TransitGateway', 'Value': 'tgw-xxxxx'}]
)
```

### CloudWatch: Daily totals for attachment

```python
get_metric_statistics(
  Namespace='AWS/TransitGateway',
  MetricName='BytesIn',
  Dimensions=[
    {'Name': 'TransitGateway', 'Value': 'tgw-xxxxx'},
    {'Name': 'TransitGatewayAttachment', 'Value': 'tgw-attach-xxxxx'}
  ],
  StartTime='2026-04-01T00:00:00Z',
  EndTime='2026-04-08T00:00:00Z',
  Period=86400,  # Daily
  Statistics=['Sum']
)
```

## Summary

- **Match time periods** — CUR lags CloudWatch; compare only overlapping hours
- **Convert units** — CUR is GB, CloudWatch is bytes
- **Query at attachment level** — Avoid double-counting at TGW aggregate level
- **Check both directions** — Billing is based on total processed, not one-way
- **Expect small variance** — < 1% difference is normal due to rounding
